"""Example data shipped with the package, so ``vme sample`` works out of the box."""

from __future__ import annotations

__all__ = ["SAMPLE_CSV", "MULTICURRENCY_CSV"]

#: A single-currency month: salary in, everyday spending out.
SAMPLE_CSV = """\
date,category,label,amount,currency,kind
2026-08-01,Income,Salary,9800.00,PLN,income
2026-08-05,Income,Freelance,1450.00,PLN,income
2026-08-02,Housing,Rent,3200.00,PLN,expense
2026-08-02,Housing,Electricity,210.40,PLN,expense
2026-08-03,Housing,Internet,79.00,PLN,expense
2026-08-04,Groceries,Biedronka,412.85,PLN,expense
2026-08-11,Groceries,Biedronka,388.20,PLN,expense
2026-08-18,Groceries,Local market,164.00,PLN,expense
2026-08-25,Groceries,Lidl,297.55,PLN,expense
2026-08-06,Transport,Monthly pass,110.00,PLN,expense
2026-08-14,Transport,Fuel,320.00,PLN,expense
2026-08-22,Transport,Parking,48.00,PLN,expense
2026-08-07,Eating out,Lunches,486.30,PLN,expense
2026-08-16,Eating out,Coffee,142.60,PLN,expense
2026-08-09,Health,Pharmacy,178.90,PLN,expense
2026-08-20,Health,Dentist,450.00,PLN,expense
2026-08-08,Subscriptions,Spotify,23.99,PLN,expense
2026-08-08,Subscriptions,Netflix,43.00,PLN,expense
2026-08-10,Subscriptions,Gym,159.00,PLN,expense
2026-08-13,Leisure,Cinema,68.00,PLN,expense
2026-08-24,Leisure,Books,127.40,PLN,expense
2026-08-28,Leisure,Concert tickets,240.00,PLN,expense
2026-08-15,Family,Kids' school trip,300.00,PLN,expense
2026-08-27,Family,Gifts,185.00,PLN,expense
"""

#: A month with money moving in four currencies -- the case a single-currency
#: budget app cannot draw. Render it with a rate for each foreign currency.
MULTICURRENCY_CSV = """\
date,category,label,amount,currency,kind
2026-08-01,Income,Salary (PL contract),9800.00,PLN,income
2026-08-12,Income,EU client invoice,1200.00,EUR,income
2026-08-20,Income,US client invoice,900.00,USD,income
2026-08-02,Housing,Rent,3200.00,PLN,expense
2026-08-02,Housing,Utilities,289.40,PLN,expense
2026-08-03,Housing,Internet,79.00,PLN,expense
2026-08-04,Groceries,Biedronka,412.85,PLN,expense
2026-08-11,Groceries,Lidl,388.20,PLN,expense
2026-08-19,Groceries,Silpo (Kyiv),1840.00,UAH,expense
2026-08-06,Travel,Flight Warsaw-Berlin,168.00,EUR,expense
2026-08-07,Travel,Hotel Berlin,245.50,EUR,expense
2026-08-08,Travel,Berlin transit pass,39.00,EUR,expense
2026-08-17,Travel,Train Kyiv-Lviv,1250.00,UAH,expense
2026-08-18,Travel,Hotel Lviv,3400.00,UAH,expense
2026-08-09,Work tools,Cloud hosting,74.00,USD,expense
2026-08-09,Work tools,Design software,22.00,USD,expense
2026-08-10,Work tools,Coworking desk,450.00,PLN,expense
2026-08-13,Eating out,Lunches Warsaw,486.30,PLN,expense
2026-08-14,Eating out,Dinner Berlin,86.40,EUR,expense
2026-08-21,Eating out,Cafes Lviv,940.00,UAH,expense
2026-08-15,Health,Pharmacy,178.90,PLN,expense
2026-08-23,Health,Travel insurance,58.00,EUR,expense
2026-08-16,Subscriptions,Spotify,23.99,PLN,expense
2026-08-16,Subscriptions,Backup storage,9.99,USD,expense
2026-08-26,Family,Gift for parents,2200.00,UAH,expense
2026-08-28,Family,Kids' school trip,300.00,PLN,expense
"""
