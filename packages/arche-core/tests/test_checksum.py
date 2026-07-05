# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for arche.detect._checksum — public-spec check-digit validators."""

from __future__ import annotations

from arche.detect._checksum import iban, isbn10, isbn13, luhn


class TestLuhn:
    def test_valid_card(self):
        assert luhn("4532015112830366") is True

    def test_single_digit_error(self):
        assert luhn("4532015112830367") is False

    def test_transposition_caught(self):
        # swap two adjacent digits of a valid number
        assert luhn("4532015112830366") is True
        assert luhn("4532015112833066") is False

    def test_non_digit_is_false(self):
        assert luhn("4532-0151") is False
        assert luhn("") is False


class TestISBN10:
    def test_valid(self):
        assert isbn10("0-306-40615-2") is True

    def test_x_check_digit(self):
        assert isbn10("0-19-852663-6") is True  # sanity: numeric check
        assert isbn10("080442957X") is True     # X == 10

    def test_invalid(self):
        assert isbn10("0-306-40615-3") is False

    def test_wrong_length(self):
        assert isbn10("12345") is False


class TestISBN13:
    def test_valid(self):
        assert isbn13("978-0-306-40615-7") is True

    def test_invalid(self):
        assert isbn13("978-0-306-40615-8") is False

    def test_wrong_length(self):
        assert isbn13("978030640615") is False


class TestIBAN:
    def test_valid(self):
        assert iban("GB82 WEST 1234 5698 7654 32") is True

    def test_invalid(self):
        assert iban("GB82 WEST 1234 5698 7654 33") is False

    def test_malformed(self):
        assert iban("12") is False
        assert iban("GBXX WEST") is False
