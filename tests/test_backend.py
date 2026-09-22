"""Run with python -m unittest discover -v. No real DB or provider requests."""
import importlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from flask_app.database import db
from flask_app.agents import cv_analyzer, match_scorer, chat_orchestrator, chat_query, cover_letter, cv_improvement
from flask_app.utils import llm_service, embedding_service, http_client, jobs_fetcher
from flask_app.utils.prompts import build_agent_prompt

# Import routes without running the application's real database initialization.
with patch.object(db, 'init_db'):
    server = importlib.import_module('flask_app.app')

CV = {'name': 'Test', 'email': None, 'skills': ['Python'], 'experience': [],
      'education': [], 'field': 'Software', 'level': 'Junior', 'summary': 'Developer'}
MATCH = {'match_score': 75, 'strengths': ['Python'], 'missing_skills': [],
         'recommendation': 'Partial Match', 'ai_comment': 'Test evaluation'}


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_patch = patch.object(db, 'DB_PATH', str(Path(self.tmp.name) / 'test.db'))
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        network = patch('requests.sessions.Session.request', side_effect=AssertionError('Network forbidden in tests'))
        network.start()
        self.addCleanup(network.stop)
        db.init_db()
        server.app.config.update(TESTING=True, SECRET_KEY='test-only', UPLOAD_FOLDER=self.tmp.name)
        server.ANALYSIS_RUNNING.clear()
        server.CHAT_RUNNING.clear()
        self.owner = server.app.test_client()
        with self.owner.session_transaction() as session:
            session['device_id'] = 'owner'
        self.pid = db.insert_cv_profile('owner', 'Private raw CV')
        self.jid = db.insert_job('Developer', 'Example', 'Python', 'https://example.org/job', 'Remote', '2026-01-01')

    def socket(self, client=None):
        client = server.socketio.test_client(server.app, flask_test_client=client or self.owner)
        self.addCleanup(lambda: client.disconnect() if client.is_connected() else None)
        return client

    def add_match(self):
        db.insert_match_result(self.pid, self.jid, .8, **MATCH)

    def test_roles_upsert_and_migration_preserve_data(self):
        with closing(db.get_connection()) as conn, conn:
            conn.execute("UPDATE llm_roles SET specific_instructions='outdated' WHERE role='Chat Orchestrator'")
        db.init_db()
        self.assertNotEqual(db.get_llm_role('Chat Orchestrator')['specific_instructions'], 'outdated')
        self.assertEqual(db.get_cv_profile(self.pid)['raw_text'], 'Private raw CV')
        self.assertEqual(len(db.get_all_llm_roles()), 6)

    def test_legacy_schema_upgrade(self):
        legacy = str(Path(self.tmp.name) / 'legacy.db')
        with closing(sqlite3.connect(legacy)) as conn, conn:
            for path in Path('flask_app/database/create_tables').glob('*.sql'):
                conn.executescript(path.read_text(encoding='utf-8'))
            conn.execute("INSERT INTO cv_profiles(device_id,raw_text) VALUES ('old','keep')")
        with patch.object(db, 'DB_PATH', legacy):
            db.init_db()
            self.assertEqual(db.get_cv_profile(1)['raw_text'], 'keep')
            self.assertEqual(db.get_cv_profile(1)['analysis_status'], 'legacy')

    def test_rest_ownership_and_private_fields(self):
        other = server.app.test_client()
        for path in (f'/api/profile/{self.pid}', f'/api/results/{self.pid}', f'/results/{self.pid}'):
            self.assertEqual(other.get(path).status_code, 403)
        body = self.owner.get(f'/api/profile/{self.pid}').get_json()
        for key in ('raw_text', 'device_id', 'embedding', 'progress_json'):
            self.assertNotIn(key, body)
        self.assertEqual(self.owner.get('/results/99999').status_code, 404)

    def test_socket_ownership(self):
        other = self.socket(server.app.test_client())
        with patch.object(server, 'route_message') as route:
            for name in ('join', 'request_chat_history', 'chat_message'):
                other.emit(name, {'profile_id': self.pid, 'message': 'hello'})
            route.assert_not_called()
        self.assertEqual(other.get_received(), [])
        self.assertEqual(db.get_chat_messages(self.pid), [])

    def test_malformed_socket_payloads(self):
        sock = self.socket()
        for payload in (None, [], {'profile_id': []}, {'profile_id': True}, {'profile_id': 2**80}):
            for event in ('join', 'chat_message', 'request_chat_history'):
                sock.emit(event, payload)
        sock.emit('chat_message', {'profile_id': self.pid, 'message': {'bad': 'type'}})
        self.assertEqual(db.get_chat_messages(self.pid), [])

    def test_reject_fake_pdf(self):
        for filename, data in [('file.txt', b'hello'), ('file.pdf', b'not a PDF')]:
            response = self.owner.post('/upload', data={'file': (io.BytesIO(data), filename)})
            self.assertEqual(response.status_code, 400)

    def test_failed_extraction_removes_temp_upload(self):
        with patch.object(server, 'extract_text_from_pdf', return_value=''):
            response = self.owner.post('/upload', data={'file': (io.BytesIO(b'%PDF-fake'), 'cv.pdf')})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(list(Path(self.tmp.name).glob('*.pdf')), [])

    def test_saved_partial_replayed_to_late_joiner(self):
        payload = {'stage': 'partial', 'message': 'partial', 'data': {'semantic_ranking': 'degraded'}}
        db.save_progress(self.pid, payload)
        sock = self.socket()
        sock.emit('join', {'profile_id': str(self.pid)})
        progress = [e['args'][0] for e in sock.get_received() if e['name'] == 'analysis_progress']
        self.assertEqual(progress, [payload])
        self.assertEqual(self.owner.get(f'/api/results/{self.pid}').get_json()['analysis'], payload)

    def test_startup_recovers_only_interrupted_runs(self):
        self.add_match()
        db.save_progress(self.pid, {'stage': 'matching', 'message': 'working'})
        other = db.insert_cv_profile('owner', 'new CV')
        done = db.insert_cv_profile('owner', 'done CV')
        db.save_progress(done, {'stage': 'complete', 'message': 'done'})
        db.recover_interrupted_analyses()
        self.assertEqual(db.get_cv_profile(self.pid)['analysis_status'], 'partial')
        self.assertEqual(db.get_cv_profile(other)['analysis_status'], 'failed')
        self.assertEqual(db.get_cv_profile(done)['analysis_status'], 'completed')
        self.assertEqual(len(db.get_match_results(self.pid)), 1)

    def test_embedding_cache_wrong_model_or_dimensions_regenerated(self):
        db.update_job_embedding(self.jid, [1, 0, 0], embedding_service.EMBEDDING_MODEL)
        with patch.object(server, 'generate_embedding', return_value=[1, 0]) as embed:
            jobs, degraded = server.search_matching_jobs([1, 0], [db.get_job(self.jid)])
        embed.assert_called_once()
        self.assertFalse(degraded)
        self.assertEqual(jobs[0]['_similarity'], 1)
        self.assertEqual(json.loads(db.get_job(self.jid)['embedding']), [1, 0])
        db.update_job_embedding(self.jid, [1, 0], 'different-model')
        with patch.object(server, 'generate_embedding', return_value=None):
            jobs, degraded = server.search_matching_jobs([1, 0], [db.get_job(self.jid)])
        self.assertTrue(degraded)
        self.assertEqual(jobs[0]['_similarity'], 0)

    def test_invalid_vectors(self):
        for vector in ([0, 0], [True, 1], [float('nan')], [float('inf')], ['1'], None, {}):
            self.assertFalse(embedding_service.valid_embedding(vector))
        self.assertEqual(embedding_service.cosine_similarity([1, 0], [1, 0, 0]), 0)

    def test_partial_workflow_persists_success(self):
        second = db.insert_job('Other', '', 'Test', 'https://example.org/2', '', '')
        jobs = [{'job_id': self.jid, 'title': 'A', '_similarity': .9},
                {'job_id': second, 'title': 'B', '_similarity': .8}]
        def score(cv, job):
            return MATCH if job['job_id'] == self.jid else None
        with patch.object(server, 'analyze_cv', return_value=CV), \
             patch.object(server, 'generate_embedding', return_value=[1, 0]), \
             patch.object(server, 'ensure_jobs_available', return_value=jobs), \
             patch.object(server, 'search_matching_jobs', return_value=(jobs, False)), \
             patch.object(server, 'score_match', side_effect=score), \
             patch.object(server.socketio, 'sleep'):
            server.analyze_and_match(self.pid, 'CV')
        profile = db.get_cv_profile(self.pid)
        self.assertEqual(profile['analysis_status'], 'partial')
        self.assertEqual(json.loads(profile['progress_json'])['data']['failed'], 1)
        self.assertEqual(len(db.get_match_results(self.pid)), 1)
        self.assertNotIn(self.pid, server.ANALYSIS_RUNNING)

    def test_failed_cv_stops_workflow(self):
        with patch.object(server, 'analyze_cv', return_value=None), \
             patch.object(server, 'ensure_jobs_available') as fetch, patch.object(server.socketio, 'sleep'):
            server.analyze_and_match(self.pid, 'CV')
        fetch.assert_not_called()
        self.assertEqual(db.get_cv_profile(self.pid)['analysis_status'], 'failed')

    def test_workflow_complete_all_failed_and_no_jobs(self):
        jobs = [{'job_id': self.jid, 'title': 'A', '_similarity': .9}]
        for selected, score, expected in ((jobs, MATCH, 'completed'), (jobs, None, 'failed'), ([], None, 'partial')):
            pid = db.insert_cv_profile('owner', 'CV')
            with patch.object(server, 'analyze_cv', return_value=CV), \
                 patch.object(server, 'generate_embedding', return_value=[1, 0]), \
                 patch.object(server, 'ensure_jobs_available', return_value=selected), \
                 patch.object(server, 'search_matching_jobs', return_value=(selected, True)), \
                 patch.object(server, 'score_match', return_value=score), \
                 patch.object(server.socketio, 'sleep'):
                server.analyze_and_match(pid, 'CV')
            self.assertEqual(db.get_cv_profile(pid)['analysis_status'], expected)

    def test_upload_success_starts_background_worker(self):
        with patch.object(server, 'extract_text_from_pdf', return_value='CV'), \
             patch.object(server.threading, 'Thread') as thread:
            response = self.owner.post('/upload', data={'file': (io.BytesIO(b'%PDF-fake'), 'cv.pdf')})
        self.assertEqual(response.status_code, 200)
        pid = response.get_json()['profile_id']
        self.assertEqual(db.get_cv_profile(pid)['analysis_status'], 'pending')
        self.assertEqual(thread.call_args.kwargs['args'], (pid, 'CV'))
        thread.return_value.start.assert_called_once()
        self.assertEqual(list(Path(self.tmp.name).glob('*.pdf')), [])

    def test_followup_context_reaches_router_and_answer(self):
        self.add_match()
        db.insert_chat_message(self.pid, 'user', 'First question')
        db.insert_chat_message(self.pid, 'agent', 'First answer', self.jid)
        sock = self.socket()
        with patch.object(server, 'route_message', return_value=('Chat Query Expert', None, 'followup')) as route, \
             patch.object(server, 'answer_question', return_value='Next answer') as answer:
            sock.emit('chat_message', {'profile_id': self.pid, 'message': 'followup'})
        history = route.call_args.kwargs['history']
        self.assertEqual(len(history), 2)
        self.assertEqual(answer.call_args.kwargs['history'], history)
        self.assertEqual(db.get_recent_chat_messages(self.pid)[-1]['message'], 'Next answer')

    def test_chat_failure_releases_busy_state(self):
        sock = self.socket()
        with patch.object(server, 'route_message', side_effect=RuntimeError('internal error')):
            sock.emit('chat_message', {'profile_id': self.pid, 'message': 'hello'})
        self.assertNotIn(self.pid, server.CHAT_RUNNING)
        self.assertTrue(any(event['name'] == 'chat_response' for event in sock.get_received()))

    def test_cv_and_score_contracts(self):
        with patch.object(cv_analyzer, 'call_llm', return_value=json.dumps(CV)):
            self.assertEqual(cv_analyzer.analyze_cv('text')['skills'], ['Python'])
        for invalid in ([], {'skills': 'Python'}, {**CV, 'skills': [7]}):
            with patch.object(cv_analyzer, 'call_llm', return_value=json.dumps(invalid)):
                self.assertIsNone(cv_analyzer.analyze_cv('text'))
        for value in (-1, 101, True, 'NaN', 'Infinity', None):
            with patch.object(match_scorer, 'call_llm', return_value=json.dumps({**MATCH, 'match_score': value})):
                self.assertIsNone(match_scorer.score_match(CV, {'title': 'Test'}))

    def test_router_allowlist_and_clarification(self):
        jobs = [{'job_id': self.jid, 'title': 'Test'}]
        for decision in ({'agent': 'Unknown', 'needs_clarification': False},
                         {'agent': 'Cover Letter Generator Expert', 'job_id': 999, 'needs_clarification': False},
                         {'agent': 'Chat Query Expert', 'needs_clarification': 'false'}):
            with patch.object(chat_orchestrator, 'call_llm', return_value=json.dumps(decision)):
                self.assertEqual(chat_orchestrator.route_message('test', jobs)[0], 'NeedsClarification')
        decision = {'agent': 'Cover Letter Generator Expert', 'job_id': self.jid, 'needs_clarification': False}
        with patch.object(chat_orchestrator, 'call_llm', return_value='```json\n'+json.dumps(decision)+'\n```'):
            self.assertEqual(chat_orchestrator.route_message('test', jobs)[1], self.jid)

    def test_router_selects_cv_improvement_and_rejects_foreign_job(self):
        jobs = [{'job_id': self.jid, 'title': 'Developer'}]
        for job_id, expected in ((self.jid, 'CV Improvement Expert'),
                                 (None, 'CV Improvement Expert'),
                                 (999, 'NeedsClarification')):
            decision = {'agent': 'CV Improvement Expert', 'job_id': job_id,
                        'needs_clarification': False}
            with patch.object(chat_orchestrator, 'call_llm', return_value=json.dumps(decision)):
                self.assertEqual(chat_orchestrator.route_message('Improve my CV', jobs)[0], expected)

    def test_cover_button_target_and_history(self):
        self.add_match()
        for i in range(8):
            db.insert_chat_message(self.pid, 'user' if i % 2 == 0 else 'agent', f'prior {i}')
        sock = self.socket()
        with patch.object(server, 'generate_cover_letter', return_value='Letter') as generate, \
             patch.object(server, 'route_message') as route:
            sock.emit('chat_message', {'profile_id': self.pid, 'job_id': self.jid, 'message': 'Write in English'})
            route.assert_not_called()
            self.assertEqual(generate.call_args.kwargs['user_message'], 'Write in English')
            self.assertEqual(len(generate.call_args.kwargs['history']), 6)
            self.assertEqual(generate.call_args.args[1]['job_id'], self.jid)
        self.assertEqual(db.get_recent_chat_messages(self.pid)[-1]['job_id'], self.jid)
        with patch.object(server, 'generate_cover_letter') as generate:
            sock.emit('chat_message', {'profile_id': self.pid, 'job_id': 999, 'message': 'write'})
            generate.assert_not_called()

    def test_selected_job_questions_and_auto_route(self):
        self.add_match()
        sock = self.socket()
        with patch.object(server, 'answer_question', return_value='Answer') as answer, \
             patch.object(server, 'generate_cover_letter') as cover, \
             patch.object(server, 'route_message', return_value=('Chat Query Expert', None, '')) as route:
            sock.emit('chat_message', {'profile_id': self.pid, 'job_id': self.jid,
                                      'action': 'ask', 'message': 'Why this job?'})
            route.assert_not_called()
            cover.assert_not_called()
            self.assertEqual(answer.call_args.kwargs['selected_job_id'], self.jid)
            sock.emit('chat_message', {'profile_id': self.pid, 'job_id': self.jid,
                                      'action': 'auto', 'message': 'Explain more'})
            self.assertEqual([job['job_id'] for job in route.call_args.args[1]], [self.jid])
            self.assertEqual(answer.call_args.kwargs['selected_job_id'], self.jid)

    def test_cv_improvement_selected_and_general_requests(self):
        self.add_match()
        sock = self.socket()
        with patch.object(server, 'suggest_cv_improvements', return_value='Suggestions') as improve, \
             patch.object(server, 'route_message', return_value=('CV Improvement Expert', None, '')) as route, \
             patch.object(server, 'generate_cover_letter') as cover:
            sock.emit('chat_message', {'profile_id': self.pid, 'job_id': self.jid,
                                      'action': 'improve_cv', 'message': 'Tailor my CV'})
            route.assert_not_called()
            cover.assert_not_called()
            self.assertEqual(improve.call_args.kwargs['match']['job_id'], self.jid)
            self.assertEqual(db.get_recent_chat_messages(self.pid)[-1]['job_id'], self.jid)
            sock.emit('chat_message', {'profile_id': self.pid, 'message': 'Improve my CV'})
            self.assertIsNone(improve.call_args.kwargs['match'])
            sock.emit('chat_message', {'profile_id': self.pid, 'job_id': self.jid,
                                      'action': 'auto', 'message': 'Improve my CV for this job'})
            self.assertEqual(improve.call_args.kwargs['match']['job_id'], self.jid)
            self.assertEqual([j['job_id'] for j in route.call_args.args[1]], [self.jid])
            sock.emit('chat_message', {'profile_id': self.pid, 'job_id': 999,
                                      'action': 'improve_cv', 'message': 'Tailor my CV'})
            self.assertEqual(improve.call_count, 3)

    def test_cv_improvement_prompt_uses_saved_facts_without_contact_details(self):
        self.add_match()
        profile = db.get_cv_profile(self.pid)
        match = db.get_match_results(self.pid)[0]
        with patch.object(cv_improvement, 'call_llm', return_value='Suggestions') as llm:
            result = cv_improvement.suggest_cv_improvements(profile, 'Improve', match=match)
        self.assertEqual(result, 'Suggestions')
        self.assertIn('Developer', llm.call_args.args[1])
        self.assertIn('Python', llm.call_args.args[1])
        self.assertNotIn('Private raw CV', llm.call_args.args[1])

    def test_chat_actions_reject_unknown_and_unmatched_jobs(self):
        self.add_match()
        sock = self.socket()
        with patch.object(server, 'answer_question') as answer, \
             patch.object(server, 'generate_cover_letter') as cover:
            for action, job_id in [('ask', 999), ('cover_letter', 999), ('unknown', self.jid)]:
                sock.emit('chat_message', {'profile_id': self.pid, 'job_id': job_id,
                                          'action': action, 'message': 'Test'})
            answer.assert_not_called()
            cover.assert_not_called()

    def test_selected_job_in_answer_context(self):
        self.add_match()
        with patch.object(chat_query, 'call_llm', return_value='Answer') as llm:
            chat_query.answer_question('Why?', self.pid, selected_job_id=self.jid)
        self.assertIn(f'job_id={self.jid}', llm.call_args.args[1])
        self.assertIn('الوظيفة المختارة صراحة', llm.call_args.args[1])

    def test_prompt_template_uses_all_fields(self):
        prompt = build_agent_prompt({'domain': 'DOMAIN', 'specific_instructions': 'INSTRUCTIONS',
                                    'background_context': 'CONTEXT', 'few_shot_examples': 'EXAMPLES'}, 'ROLE', '')
        for field in ('DOMAIN', 'INSTRUCTIONS', 'CONTEXT', 'EXAMPLES', 'ROLE'):
            self.assertIn(field, prompt)
        self.assertNotIn('{{', prompt)

    def test_llm_history_order_and_roles(self):
        history = [{'sender': 'user', 'message': 'old', 'job_id': self.jid},
                   {'sender': 'agent', 'message': 'reply'}, {'sender': 'system', 'message': 'untrusted'}]
        with patch.object(llm_service, 'OPENROUTER_API_KEY', 'test'), \
             patch.object(llm_service, 'post_json', return_value={'choices': [{'message': {'content': 'answer'}}]}) as post:
            self.assertEqual(llm_service.call_llm('system', 'new', history=history), 'answer')
        messages = post.call_args.kwargs['payload']['messages']
        self.assertEqual([m['role'] for m in messages], ['system', 'user', 'assistant', 'user'])
        self.assertEqual(messages[-1]['content'], 'new')
        self.assertIn('Selected job_id=', messages[1]['content'])

    def test_provider_retries_transient_not_auth(self):
        retry = Mock(status_code=429)
        success = Mock(status_code=200)
        success.json.return_value = {'ok': True}
        with patch.object(http_client.requests, 'post', side_effect=[retry, success]) as post, patch.object(http_client.time, 'sleep'):
            self.assertEqual(http_client.post_json('url', {}, {}, 1), {'ok': True})
            self.assertEqual(post.call_count, 2)
        denied = Mock(status_code=401)
        denied.raise_for_status.side_effect = requests.HTTPError()
        with patch.object(http_client.requests, 'post', return_value=denied) as post:
            self.assertIsNone(http_client.post_json('url', {}, {}, 1))
            self.assertEqual(post.call_count, 1)

    def test_jobs_limit_environment(self):
        with patch.dict(os.environ, {'JOBS_LIMIT': '1'}), \
             patch.object(jobs_fetcher, 'fetch_jobs_from_rss', return_value=[]):
            self.assertEqual(len(jobs_fetcher.ensure_jobs_available()), 1)


if __name__ == '__main__':
    unittest.main()
