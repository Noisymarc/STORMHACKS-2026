"""Real TiDB regression checks using the standard-library test runner.

Run: python -m unittest discover -s tests -p test_glossary_matching.py -v
Only isolated temporary user rows are inserted and deleted.
"""
import os
import unittest
import uuid
from pathlib import Path

from dotenv import load_dotenv

from backend.tidb import MemoryStore

load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)


@unittest.skipUnless(all(os.getenv(k) for k in ('TIDB_HOST', 'TIDB_USER', 'TIDB_PASSWORD')),
                     'TiDB connection settings are required')
class GlossaryMatchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = MemoryStore.from_env()
        cls.store.init_schema()

    @classmethod
    def tearDownClass(cls):
        cls.store.engine.dispose()

    def setUp(self):
        self.user = str(uuid.uuid4())

    def tearDown(self):
        self.store.delete_user_memories(self.user)

    def test_same_word_wrong_sense_is_rejected_but_paraphrase_survives(self):
        self.store.add_memory(self.user, 'feedback loop',
            context='A feedback loop returns the output of a system to influence its next input.')
        self.assertEqual(self.store.search_relevant_memories(self.user,
            'The university changed its course feedback form this semester.'), [])
        self.assertEqual(self.store.search_relevant_memories(self.user,
            'Students complete a feedback form about the course.'), [])
        results = self.store.search_relevant_memories(self.user,
            'The result influences the next action, which then changes the next result.')
        self.assertEqual([m.content for m in results], ['feedback loop'])

    def test_weak_term_paraphrase_is_preserved_with_context(self):
        self.store.add_memory(self.user, 'opportunity cost',
            context='An opportunity cost is the value of the next best alternative we give up.')
        results = self.store.search_relevant_memories(self.user,
            'Choosing this plan means sacrificing the value of our second-best option.')
        self.assertEqual([m.content for m in results], ['opportunity cost'])

    def test_legacy_entry_needs_stronger_similarity(self):
        self.store.add_memory(self.user, 'feedback loop')
        self.assertEqual(self.store.search_relevant_memories(self.user,
            'The university changed its course feedback form this semester.'), [])
        results = self.store.search_relevant_memories(self.user,
            "A feedback loop sends a system's output back in as input.")
        self.assertEqual([m.content for m in results], ['feedback loop'])

    def test_diagnostic_search_keeps_unfiltered_rankings(self):
        self.store.add_memory(self.user, 'feedback loop', context='A feedback loop changes future input.')
        results = self.store.search_relevant_memories(self.user,
            'The university changed its course feedback form this semester.', min_similarity=None)
        self.assertEqual([m.content for m in results], ['feedback loop'])

    def test_other_user_and_language_are_excluded(self):
        self.store.add_memory(self.user, 'feedback loop', target_lang='ja',
            context='A feedback loop returns output as input.')
        sentence = "A feedback loop sends a system's output back in as input."
        self.assertEqual(self.store.search_relevant_memories(str(uuid.uuid4()), sentence), [])
        self.assertEqual(self.store.search_relevant_memories(self.user, sentence, target_lang='en'), [])

    def test_original_growth_example_still_matches(self):
        self.store.add_memory(self.user, 'exponential growth',
            context='The population grows by the same percentage each period.')
        results = self.store.search_relevant_memories(self.user,
            'The number of users is growing exponentially.')
        self.assertEqual([m.content for m in results], ['exponential growth'])


if __name__ == '__main__':
    unittest.main()
