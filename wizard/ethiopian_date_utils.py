# -*- coding: utf-8 -*-
from datetime import date, datetime

# Ethiopian Month Names in Amharic & English Transliteration
ETHIOPIAN_MONTHS_AMHARIC = [
    '',
    'መስከረም', 'ጥቅምት', 'ኅዳር', 'ታኅሣሥ', 'ጥር', 'የካቲት',
    'መጋቢት', 'ሚያዝያ', 'ግንቦት', 'ሰኔ', 'ሐምሌ', 'ነሐሴ', 'ጳጉሜ'
]

ETHIOPIAN_MONTHS_EN = [
    '',
    'Meskerem', 'Tikimt', 'Hidar', 'Tahsas', 'Tir', 'Yekatit',
    'Megabit', 'Miyazya', 'Ginbot', 'Sene', 'Hamle', 'Nehase', 'Pagume'
]

ETHIOPIAN_MONTH_SELECTION = [
    ('1', 'መስከረም (Meskerem)'),
    ('2', 'ጥቅምት (Tikimt)'),
    ('3', 'ኅዳር (Hidar)'),
    ('4', 'ታኅሣሥ (Tahsas)'),
    ('5', 'ጥር (Tir)'),
    ('6', 'የካቲት (Yekatit)'),
    ('7', 'መጋቢት (Megabit)'),
    ('8', 'ሚያዝያ (Miyazya)'),
    ('9', 'ግንቦት (Ginbot)'),
    ('10', 'ሰኔ (Sene)'),
    ('11', 'ሐምሌ (Hamle)'),
    ('12', 'ነሐሴ (Nehase)'),
    ('13', 'ጳጉሜ (Pagume)'),
]


def gregorian_to_jdn(year, month, day):
    """Converts Gregorian date to Julian Day Number (JDN)"""
    a = (14 - month) // 12
    y = year + 4800 - a
    m = month + 12 * a - 3
    return day + ((153 * m + 2) // 5) + 365 * y + (y // 4) - (y // 100) + (y // 400) - 32045


def jdn_to_ethiopian(jdn):
    """Converts Julian Day Number (JDN) to Ethiopian date tuple (year, month, day)"""
    r = (jdn - 1723856) % 1461
    n = (r % 365) + 365 * (r // 1460)
    year = 4 * ((jdn - 1723856) // 1461) + (r // 365) - (r // 1460)
    month = (n // 30) + 1
    day = (n % 30) + 1
    return year, month, day


def gregorian_to_ethiopian(g_date):
    """
    Converts a Python date/datetime or ISO date string to Ethiopian (year, month, day).
    """
    if not g_date:
        return None
    if isinstance(g_date, str):
        g_date = datetime.strptime(g_date[:10], '%Y-%m-%d').date()
    elif isinstance(g_date, datetime):
        g_date = g_date.date()

    jdn = gregorian_to_jdn(g_date.year, g_date.month, g_date.day)
    return jdn_to_ethiopian(jdn)


def format_ethiopian_month_year(g_date):
    """
    Returns e.g. 'መስከረም 2019'
    """
    eth_date = gregorian_to_ethiopian(g_date)
    if not eth_date:
        return ''
    ey, em, _ = eth_date
    m_name = ETHIOPIAN_MONTHS_AMHARIC[em] if 1 <= em <= 13 else ''
    return f"{m_name} {ey}".strip()
