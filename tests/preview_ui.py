"""Isolated manual UI fixture: python -B -m tests.preview_ui (localhost:5055).

Synthetic data and mocked AI only; never imports this route into the real app.
"""
from flask import redirect, session
from tests.test_backend import BackendTests, CV, db, server


def main():
    fixture = BackendTests()
    fixture.setUp()
    db.update_cv_profile_analysis(fixture.pid, embedding=[1, 0], **{**CV, 'name': 'سارة أحمد'})
    fixture.add_match()
    second = db.insert_job('Junior Data Analyst', 'Studio Labs',
                           'تحليل البيانات باستخدام Python وSQL والعمل مع الفريق.',
                           'https://example.org/analyst', 'Remote', '2026-09-01')
    db.insert_match_result(fixture.pid, second, .72, 68, ['Python', 'تحليل البيانات'],
                           ['SQL', 'Power BI'], 'Partial Match',
                           'لديك أساس مناسب، وتطوير مهارات SQL سيساعدك في هذه الوظيفة.')
    db.save_progress(fixture.pid, {'stage': 'complete', 'message': 'اكتمل تحليل سيرتك ومطابقة الفرص.',
                                  'data': {'semantic_ranking': 'available'}})
    server.answer_question = lambda *args, **kwargs: 'إجابة تجريبية: مهارة Python من نقاط قوتك لهذه الوظيفة.'
    server.generate_cover_letter = lambda *args, **kwargs: 'خطاب تجريبي للوظيفة المختارة، وليس استجابة من خدمة AI.'
    server.suggest_cv_improvements = lambda *args, **kwargs: 'اقتراح تجريبي: أبرز مشروع Python الموجود في سيرتك عند التقديم لهذه الوظيفة.'
    server.route_message = lambda *args, **kwargs: ('Chat Query Expert', None, 'preview')

    @server.app.get('/_preview')
    def preview():
        session['device_id'] = 'owner'
        return redirect(f'/results/{fixture.pid}')

    try:
        server.socketio.run(server.app, host='127.0.0.1', port=5055, debug=False,
                            allow_unsafe_werkzeug=True)
    finally:
        fixture.doCleanups()


if __name__ == '__main__':
    main()
