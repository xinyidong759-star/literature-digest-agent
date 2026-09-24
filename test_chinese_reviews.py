import os
import unittest
from unittest.mock import patch
import literature_digest_agent as agent

LABELS = ('中文题目', '中文摘要', '中文总结', '研究问题', '方法与数据', '主要发现', '评论与待核实问题', '证据范围')
CONTENT = '\n'.join(f'- {label}：中文测试内容' for label in LABELS)

class ChineseReviewTests(unittest.TestCase):
    def test_missing_key_stops_before_search(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(agent, 'search_openalex') as search:
            with self.assertRaisesRegex(RuntimeError, 'OPENAI_API_KEY'):
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
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fake-test-key'}):
            for content, reason in [(CONTENT, 'stop'), ('English only', 'stop'), (CONTENT, 'length'), ('', 'stop')]:
                with self.subTest(reason=reason, content=content), patch.object(agent, 'http_post_json', return_value={'choices': [{'finish_reason': reason, 'message': {'content': content}}]}):
                    if content == CONTENT and reason == 'stop':
                        self.assertEqual(agent.generate_llm_review({}, {}), CONTENT)
                    else:
                        with self.assertRaises(RuntimeError):
                            agent.generate_llm_review({}, {})

    def test_failed_generation_blocks_required_report(self):
        config = {'llm': {'enabled': True, 'required': True, 'max_reviews': 0}}
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fake-test-key'}), patch.object(agent, 'generate_llm_review', side_effect=RuntimeError('test failure')), patch.object(agent.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'will not be sent'):
                agent.add_llm_reviews(config, [{'title': 'example'}])

    def test_chinese_is_in_report_and_email_html(self):
        paper = {'title': 'example', 'llm_review': CONTENT, 'abstract': 'Original abstract'}
        report = agent.build_report({}, [paper], '2026-09-01', '2026-09-24')
        for label in LABELS:
            self.assertIn(label, report)
            self.assertIn(label, agent.markdown_to_simple_html(report))
        self.assertIn('Original abstract', paper['abstract'])

if __name__ == '__main__':
    unittest.main()
