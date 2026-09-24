import os
import unittest
from unittest.mock import patch
import literature_digest_agent as agent

LABELS = ('中文题目', '中文摘要', '中文总结', '研究问题', '方法与数据', '主要发现', '评论与待核实问题', '证据范围')
CONTENT = '\n'.join(f'- {label}：中文测试内容' for label in LABELS)

class ChineseReviewTests(unittest.TestCase):
    def test_missing_key_stops_before_search(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(agent, 'search_openalex') as search:
            with self.assertRaisesRegex(RuntimeError, 'DEEPSEEK_API_KEY'):
                agent.run({'llm': {'enabled': True, 'required': True}}, None)
            search.assert_not_called()

    def test_all_report_papers_and_same_order(self):
        papers = [{'title': str(i), 'modules': ['a', 'b'], 'relevance_score': 1, 'source_quality_score': i} for i in range(24)]
        config = {'modules': [{'name': 'a', 'max_items': 18}, {'name': 'b', 'max_items': 24}], 'llm': {'enabled': True, 'required': True, 'max_reviews': 0}}
        targets = agent.collect_review_targets(config, papers)
        self.assertEqual(len(targets), 24)
        self.assertEqual(targets, list(reversed(papers)))
        config['llm']['max_reviews'] = 12
        with self.assertRaisesRegex(RuntimeError, 'cannot cover'):
            agent.collect_review_targets(config, papers)

    def test_api_response_validation(self):
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'fake-test-key'}, clear=True):
            for content, reason in [(CONTENT, 'stop'), ('English only', 'stop'), (CONTENT, 'length'), ('', 'stop')]:
                with self.subTest(reason=reason, content=content), patch.object(agent, 'http_post_json', return_value={'choices': [{'finish_reason': reason, 'message': {'content': content}}]}):
                    if content == CONTENT and reason == 'stop':
                        self.assertEqual(agent.generate_llm_review({}, {}), CONTENT)
                    else:
                        with self.assertRaises(RuntimeError):
                            agent.generate_llm_review({}, {})

    def test_failed_generation_blocks_required_report(self):
        config = {'llm': {'enabled': True, 'required': True, 'max_reviews': 0}}
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'fake-test-key'}), patch.object(agent, 'generate_llm_review', side_effect=RuntimeError('test failure')), patch.object(agent.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'will not be sent'):
                agent.add_llm_reviews(config, [{'title': 'example'}])

    def test_deepseek_request_and_final_content(self):
        response = {'choices': [{'finish_reason': 'stop', 'message': {'content': CONTENT, 'reasoning_content': 'private reasoning'}}]}
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'fake-test-key'}, clear=True), patch.object(agent, 'http_post_json', return_value=response) as post:
            self.assertEqual(agent.generate_llm_review({}, {}), CONTENT)
            args, kwargs = post.call_args
            self.assertEqual(args[0], 'https://api.deepseek.com/chat/completions')
            self.assertEqual(args[1]['model'], 'deepseek-flash')
            self.assertEqual(args[1]['thinking'], {'type': 'enabled'})
            self.assertEqual(args[1]['reasoning_effort'], 'high')
            self.assertFalse(args[1]['stream'])
            self.assertNotIn('temperature', args[1])
            self.assertEqual(kwargs['timeout'], 300)
            self.assertEqual(kwargs['headers']['Authorization'], 'Bearer fake-test-key')

    def test_model_override_and_non_thinking(self):
        response = {'choices': [{'finish_reason': 'stop', 'message': {'content': CONTENT}}]}
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'fake-test-key', 'DEEPSEEK_MODEL': 'custom-model', 'OPENAI_MODEL': 'unused-model'}, clear=True), patch.object(agent, 'http_post_json', return_value=response) as post:
            agent.generate_llm_review({}, {'llm': {'thinking': 'disabled', 'temperature': 0.3, 'timeout': 120}})
            payload = post.call_args.args[1]
            self.assertEqual(payload['model'], 'custom-model')
            self.assertEqual(payload['thinking'], {'type': 'disabled'})
            self.assertEqual(payload['temperature'], 0.3)
            self.assertNotIn('reasoning_effort', payload)
            self.assertEqual(post.call_args.kwargs['timeout'], 120)

    def test_openai_key_does_not_replace_deepseek_key(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'unused-key'}, clear=True), patch.object(agent, 'http_post_json') as post:
            with self.assertRaisesRegex(RuntimeError, 'DEEPSEEK_API_KEY'):
                agent.generate_llm_review({}, {})
            post.assert_not_called()

    def test_chinese_is_in_report_and_email_html(self):
        paper = {'title': 'example', 'llm_review': CONTENT, 'abstract': 'Original abstract'}
        report = agent.build_report({}, [paper], '2026-09-01', '2026-09-24')
        for label in LABELS:
            self.assertIn(label, report)
            self.assertIn(label, agent.markdown_to_simple_html(report))
        self.assertIn('Original abstract', paper['abstract'])

if __name__ == '__main__':
    unittest.main()
