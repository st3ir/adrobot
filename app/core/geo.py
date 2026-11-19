"""ISO 3166-1 alpha-2 country reference data.

Kept as a single compact table so the geo code accepted by the campaign
creator is validated against a real list instead of a loose regex, and so the
UI can offer human-readable country names without an extra dependency.
"""

from __future__ import annotations

from types import MappingProxyType

_RAW = """
AD:Andorra|AE:United Arab Emirates|AF:Afghanistan|AG:Antigua and Barbuda|AI:Anguilla
AL:Albania|AM:Armenia|AO:Angola|AQ:Antarctica|AR:Argentina|AS:American Samoa|AT:Austria
AU:Australia|AW:Aruba|AX:Aland Islands|AZ:Azerbaijan|BA:Bosnia and Herzegovina
BB:Barbados|BD:Bangladesh|BE:Belgium|BF:Burkina Faso|BG:Bulgaria|BH:Bahrain|BI:Burundi
BJ:Benin|BL:Saint Barthelemy|BM:Bermuda|BN:Brunei|BO:Bolivia|BQ:Caribbean Netherlands
BR:Brazil|BS:Bahamas|BT:Bhutan|BV:Bouvet Island|BW:Botswana|BY:Belarus|BZ:Belize
CA:Canada|CC:Cocos Islands|CD:DR Congo|CF:Central African Republic|CG:Congo
CH:Switzerland|CI:Cote d'Ivoire|CK:Cook Islands|CL:Chile|CM:Cameroon|CN:China
CO:Colombia|CR:Costa Rica|CU:Cuba|CV:Cape Verde|CW:Curacao|CX:Christmas Island
CY:Cyprus|CZ:Czechia|DE:Germany|DJ:Djibouti|DK:Denmark|DM:Dominica
DO:Dominican Republic|DZ:Algeria|EC:Ecuador|EE:Estonia|EG:Egypt|EH:Western Sahara
ER:Eritrea|ES:Spain|ET:Ethiopia|FI:Finland|FJ:Fiji|FK:Falkland Islands|FM:Micronesia
FO:Faroe Islands|FR:France|GA:Gabon|GB:United Kingdom|GD:Grenada|GE:Georgia
GF:French Guiana|GG:Guernsey|GH:Ghana|GI:Gibraltar|GL:Greenland|GM:Gambia|GN:Guinea
GP:Guadeloupe|GQ:Equatorial Guinea|GR:Greece|GS:South Georgia|GT:Guatemala|GU:Guam
GW:Guinea-Bissau|GY:Guyana|HK:Hong Kong|HM:Heard and McDonald Islands|HN:Honduras
HR:Croatia|HT:Haiti|HU:Hungary|ID:Indonesia|IE:Ireland|IL:Israel|IM:Isle of Man
IN:India|IO:British Indian Ocean Territory|IQ:Iraq|IR:Iran|IS:Iceland|IT:Italy
JE:Jersey|JM:Jamaica|JO:Jordan|JP:Japan|KE:Kenya|KG:Kyrgyzstan|KH:Cambodia|KI:Kiribati
KM:Comoros|KN:Saint Kitts and Nevis|KP:North Korea|KR:South Korea|KW:Kuwait
KY:Cayman Islands|KZ:Kazakhstan|LA:Laos|LB:Lebanon|LC:Saint Lucia|LI:Liechtenstein
LK:Sri Lanka|LR:Liberia|LS:Lesotho|LT:Lithuania|LU:Luxembourg|LV:Latvia|LY:Libya
MA:Morocco|MC:Monaco|MD:Moldova|ME:Montenegro|MF:Saint Martin|MG:Madagascar
MH:Marshall Islands|MK:North Macedonia|ML:Mali|MM:Myanmar|MN:Mongolia|MO:Macao
MP:Northern Mariana Islands|MQ:Martinique|MR:Mauritania|MS:Montserrat|MT:Malta
MU:Mauritius|MV:Maldives|MW:Malawi|MX:Mexico|MY:Malaysia|MZ:Mozambique|NA:Namibia
NC:New Caledonia|NE:Niger|NF:Norfolk Island|NG:Nigeria|NI:Nicaragua|NL:Netherlands
NO:Norway|NP:Nepal|NR:Nauru|NU:Niue|NZ:New Zealand|OM:Oman|PA:Panama|PE:Peru
PF:French Polynesia|PG:Papua New Guinea|PH:Philippines|PK:Pakistan|PL:Poland
PM:Saint Pierre and Miquelon|PN:Pitcairn|PR:Puerto Rico|PS:Palestine|PT:Portugal
PW:Palau|PY:Paraguay|QA:Qatar|RE:Reunion|RO:Romania|RS:Serbia|RU:Russia|RW:Rwanda
SA:Saudi Arabia|SB:Solomon Islands|SC:Seychelles|SD:Sudan|SE:Sweden|SG:Singapore
SH:Saint Helena|SI:Slovenia|SJ:Svalbard and Jan Mayen|SK:Slovakia|SL:Sierra Leone
SM:San Marino|SN:Senegal|SO:Somalia|SR:Suriname|SS:South Sudan|ST:Sao Tome and Principe
SV:El Salvador|SX:Sint Maarten|SY:Syria|SZ:Eswatini|TC:Turks and Caicos Islands|TD:Chad
TF:French Southern Territories|TG:Togo|TH:Thailand|TJ:Tajikistan|TK:Tokelau
TL:Timor-Leste|TM:Turkmenistan|TN:Tunisia|TO:Tonga|TR:Turkiye|TT:Trinidad and Tobago
TV:Tuvalu|TW:Taiwan|TZ:Tanzania|UA:Ukraine|UG:Uganda|UM:US Minor Outlying Islands
US:United States|UY:Uruguay|UZ:Uzbekistan|VA:Vatican City|VC:Saint Vincent
VE:Venezuela|VG:British Virgin Islands|VI:US Virgin Islands|VN:Vietnam|VU:Vanuatu
WF:Wallis and Futuna|WS:Samoa|YE:Yemen|YT:Mayotte|ZA:South Africa|ZM:Zambia|ZW:Zimbabwe
"""


def _parse() -> dict[str, str]:
    table: dict[str, str] = {}
    for chunk in _RAW.replace("\n", "|").split("|"):
        entry = chunk.strip()
        if not entry:
            continue
        code, _, name = entry.partition(":")
        table[code] = name
    return table


COUNTRIES: MappingProxyType[str, str] = MappingProxyType(_parse())
COUNTRY_CODES: frozenset[str] = frozenset(COUNTRIES)


def normalize_country_code(value: str) -> str | None:
    """Return the canonical alpha-2 code, or ``None`` when unknown."""
    code = value.strip().upper()
    return code if code in COUNTRY_CODES else None


def country_name(code: str) -> str:
    return COUNTRIES.get(code.upper(), code.upper())
