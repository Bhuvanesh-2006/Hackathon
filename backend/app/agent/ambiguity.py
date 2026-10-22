"""Deterministic ambiguity guard for well-known ambiguous phrasings.

Runs before the LLM so designated ambiguous questions always get a clarifying question, no
matter which provider is configured. The LLM can additionally decide to ask for clarification.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

METRIC_WORDS = re.compile(
    r"\b(revenue|sales value|spend|spent|spending|gross|net|invoices?|orders?|units?|quantity|"
    r"value|money|£|gbp|frequency|number of|count|returns?|returned|cancel\w*)\b",
    re.I,
)
CUSTOMER_AMBIGUOUS = re.compile(r"\b(best|top|most valuable|biggest|most important|key|largest|loyal)\b.*\bcustomers?\b", re.I)
PRODUCT_AMBIGUOUS = re.compile(
    r"\b(best[- ]?sell\w*|bestsellers?|most popular|best|top|biggest|leading)\b.*\b(products?|items?|sellers?|lines?)\b"
    r"|\bbest[- ]?sellers?\b|\bbest[- ]?selling\b",
    re.I,
)


# "On which date did the product generate maximum revenue?" asks for a date about an unnamed product.
DATE_QUESTION = re.compile(r"\b(which|what|on which)\s+(invoice\s+)?(date|day)\b|\bwhen\b", re.I)
UNNAMED_PRODUCT = re.compile(r"\b(the|a|our)\s+(product|item)\b|\bproducts?\b", re.I)
STOCK_CODE = re.compile(r"\b\d{5}[A-Za-z]{0,2}\b")
DATE_OPTIONS = [
    "The single day with the highest revenue across all products",
    "The best day for each of the top 10 products",
    "The single product and day with the highest revenue",
]


# "What is the max revenue?" names an extreme but not what it is measured over.
EXTREME_WORDS = re.compile(r"\b(max|maximum|highest|peak|largest|biggest|top|best|record)\b", re.I)
REVENUE_WORDS = re.compile(r"\b(revenue|sales|turnover|takings)\b", re.I)
DIMENSION_WORDS = re.compile(
    r"\b(products?|items?|sku|stock|customers?|clients?|countr(y|ies)|markets?|regions?|months?|monthly|days?|daily|"
    r"dates?|weeks?|weekly|weekdays?|quarters?|years?|yearly|invoices?|orders?|transactions?|baskets?)\b",
    re.I,
)
EXTREME_OPTIONS = [
    "Month with the highest net revenue",
    "Day with the highest net revenue",
    "Product with the highest net revenue",
    "Customer with the highest net revenue",
    "Country with the highest net revenue",
    "Largest single order (invoice)",
]


@dataclass
class Clarification:
    question: str
    options: list[str]


def check_ambiguity(question: str) -> Clarification | None:
    if DATE_QUESTION.search(question) and UNNAMED_PRODUCT.search(question) and not STOCK_CODE.search(question):
        return Clarification("Which do you mean? The product is not named, so this can be read three ways.", DATE_OPTIONS)
    if EXTREME_WORDS.search(question) and REVENUE_WORDS.search(question) and not DIMENSION_WORDS.search(question):
        return Clarification("Highest revenue measured over what? Pick the level to compare.", EXTREME_OPTIONS)
    if METRIC_WORDS.search(question):
        return None
    if CUSTOMER_AMBIGUOUS.search(question):
        return Clarification(
            "Should I rank customers by net revenue, gross revenue, or number of invoices?",
            ["Net revenue (sales minus cancellations)", "Gross revenue (before cancellations)", "Number of invoices"],
        )
    if PRODUCT_AMBIGUOUS.search(question):
        return Clarification(
            "Should I rank products by net revenue or by units sold?",
            ["Net revenue (sales minus cancellations)", "Units sold"],
        )
    return None
