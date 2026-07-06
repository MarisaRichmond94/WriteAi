"""Unit tests for src/quotesnap.py — sentence snapping for source_quotes.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_quotesnap -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.quotesnap import locate_quote, normalize_quote, snap_quote_to_sentences


class TestLocateQuote(unittest.TestCase):
    def test_exact_substring(self):
        text = "She ran to the door. He followed her out."
        self.assertEqual(locate_quote("He followed her out.", text), (21, 41))

    def test_curly_vs_straight_quotes_and_whitespace(self):
        # Model straightens curly quotes and collapses whitespace; the span
        # must still map back to the original text.
        text = "“I  saw him,”  she said.\nThen she left."
        span = locate_quote('"I saw him," she said.', text)
        self.assertIsNotNone(span)
        self.assertEqual(text[span[0]:span[1]], "“I  saw him,”  she said.")

    def test_ellipsis_character(self):
        text = "He trailed off… then nothing."
        span = locate_quote("He trailed off... then nothing.", text)
        self.assertEqual(text[span[0]:span[1]], text)

    def test_missing_quote(self):
        self.assertIsNone(locate_quote("not here", "Some other text."))


class TestSnapQuoteToSentences(unittest.TestCase):
    def test_already_aligned_returned_unchanged(self):
        text = "The rain had stopped. The storm is coming. Nobody moved."
        quote = "The storm is coming."
        self.assertEqual(snap_quote_to_sentences(quote, text), quote)

    def test_mid_sentence_start_and_end(self):
        text = "The rain had stopped. The storm is coming for all of us. Nobody moved."
        self.assertEqual(
            snap_quote_to_sentences("storm is coming for all", text),
            "The storm is coming for all of us.")

    def test_quote_starting_mid_dialogue(self):
        # Snapping pulls in the opening of the spoken sentence, including the
        # opening quote mark and the dialogue's own start.
        text = ('Marcus lowered his voice. “You can’t keep running from this, '
                'Elena, and the storm is already here.” She looked away.')
        self.assertEqual(
            snap_quote_to_sentences("the storm is already here", text),
            "“You can’t keep running from this, Elena, "
            "and the storm is already here.”")

    def test_ender_inside_quotes_dialogue_tag_stays_attached(self):
        # `"Stop!" she said.` — the ! inside quotes does not end the sentence,
        # so the tag rides along in both directions.
        text = 'He froze. "Stop right there!" she said quietly. Then silence.'
        self.assertEqual(
            snap_quote_to_sentences("she said quietly", text),
            '"Stop right there!" she said quietly.')

    def test_ender_inside_quotes_before_capital_ends_sentence(self):
        text = '"Stop right there!" The guard stepped forward into the light.'
        self.assertEqual(
            snap_quote_to_sentences("stepped forward into", text),
            "The guard stepped forward into the light.")

    def test_ellipsis_mid_sentence_stays_inside(self):
        text = ("She hesitated… the words would not come to her at all. "
                "He waited by the door.")
        self.assertEqual(
            snap_quote_to_sentences("the words would not come", text),
            "She hesitated… the words would not come to her at all.")

    def test_em_dash_interruption_stays_inside(self):
        text = 'Cold. "I never meant—" she began, but he was already gone. Done.'
        self.assertEqual(
            snap_quote_to_sentences("he was already gone", text),
            '"I never meant—" she began, but he was already gone.')

    def test_abbreviation_does_not_end_sentence(self):
        text = "They left. Mr. Calloway kept the ledger hidden for years. Fine."
        self.assertEqual(
            snap_quote_to_sentences("kept the ledger hidden", text),
            "Mr. Calloway kept the ledger hidden for years.")

    def test_newline_is_a_hard_boundary(self):
        text = "a fragment with no ender\nThe next paragraph starts here."
        self.assertEqual(
            snap_quote_to_sentences("fragment with no ender", text),
            "a fragment with no ender")

    def test_trailing_closing_quote_pulled_in(self):
        text = 'She said, "The night was darker than it had any right to be."'
        self.assertEqual(
            snap_quote_to_sentences(
                "The night was darker than it had any right to be.", text),
            'She said, "The night was darker than it had any right to be."')

    def test_cap_max_chars_keeps_original(self):
        long_sentence = "He remembered " + "the long road and " * 30 + "the end."
        text = "Short one. " + long_sentence
        quote = "the long road"
        self.assertEqual(snap_quote_to_sentences(quote, text), quote)

    def test_cap_growth_factor_keeps_original(self):
        text = ("The letter said everything she had feared it would say and "
                "then said a great deal more besides that. Next.")
        quote = "feared"  # snapping would be far beyond 3x len("feared")
        self.assertEqual(snap_quote_to_sentences(quote, text), quote)

    def test_unlocatable_quote_returned_unchanged(self):
        self.assertEqual(
            snap_quote_to_sentences("phantom words", "Real text only here."),
            "phantom words")

    def test_quote_spanning_paragraph_break_rendered_single_line(self):
        # The original quote may span a newline (models collapse whitespace
        # when copying); the snapped result must come back single-line.
        text = "She promised. But if his dad finds out…\nHe might actually kill him. End."
        snapped = snap_quote_to_sentences(
            "if his dad finds out… He might actually kill him.", text)
        self.assertEqual(
            snapped, "But if his dad finds out… He might actually kill him.")
        self.assertNotIn("\n", snapped)

    def test_snapped_text_is_verbatim_slice(self):
        # The snapped quote must satisfy the extractor's verifier: normalized,
        # it is a substring of the normalized chunk text.
        text = "It began to rain. “He was never coming back,” she realized. End."
        snapped = snap_quote_to_sentences("never coming back", text)
        self.assertEqual(snapped, "“He was never coming back,” she realized.")
        self.assertIn(normalize_quote(snapped), normalize_quote(text))


if __name__ == "__main__":
    unittest.main()
