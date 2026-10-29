"""Field-aware import equivalence. Originals remain available as source evidence."""
import re,unicodedata
from urllib.parse import urlsplit, urlunsplit

EMAIL=re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b',re.I)
MONTHS={name:i for i,names in enumerate(('jan january','feb february','mar march','apr april','may','jun june','jul july','aug august','sep sept september','oct october','nov november','dec december'),1) for name in names.split()}

NAME_SUFFIXES={'jr':'Jr','sr':'Sr',**{v.casefold():v for v in ('II','III','IV','V','VI','VII','VIII','IX','X')}}
def name_core(value):
    words=unicodedata.normalize('NFC',' '.join(str(value or '').split())).split()
    while words and words[-1].strip('.,').casefold() in NAME_SUFFIXES:words.pop()
    return ' '.join(words)

def preferred_name_case(value):
    core=name_core(value)
    return bool(core and not core.isupper() and not core.islower() and any(c.isupper() for c in core) and any(c.islower() for c in core))

def personal_name(value):
    value=unicodedata.normalize('NFC',' '.join(str(value or '').split()))
    core=name_core(value)
    # Respect casing already supplied by a person/source, including McDonald,
    # de la Cruz and intentionally styled names. Only uniform case is changed.
    if not core or not (core.isupper() or core.islower()):return value
    words=value.split()
    def word(token,index):
        suffix=token.strip('.,').casefold()
        if index==len(words)-1 and suffix in NAME_SUFFIXES:
            return re.sub(r'[^\W\d_]+',lambda m:NAME_SUFFIXES[suffix],token,count=1)
        if re.fullmatch(r'(?:[^\W\d_]\.)+',token,re.UNICODE):return token.upper()
        if index==0 and token.isalpha() and len(token)<=2 and token.isupper():return token
        def capitalize(match):
            part=match.group();formatted=part[:1].upper()+part[1:].lower()
            if len(part)>4 and formatted.startswith('Mc'):formatted='Mc'+formatted[2:3].upper()+formatted[3:]
            return formatted
        return re.sub(r'[^\W\d_]+',capitalize,token)
    return ' '.join(word(token,index) for index,token in enumerate(words))

def phone(value):
    value=str(value or '').strip()
    match=re.search(r'\s*(?:ext\.?|extension|x|#)\s*(\d+)\s*$',value,re.I)
    extension=match.group(1) if match else ''
    base=value[:match.start()] if match else value
    digits=re.sub(r'\D','',base)
    if len(digits)==11 and digits.startswith('1'):digits=digits[1:]
    if len(digits)==10 and digits[0] in '23456789' and digits[3] in '23456789' and (not base.startswith('+') or re.sub(r'\D','',base).startswith('1')):
        return f'({digits[:3]}) {digits[3:6]}-{digits[6:]}' + (' ext. '+extension if extension else '')
    if base.startswith('+') and 7<=len(digits)<=15:
        return '+'+digits+(' ext. '+extension if extension else '')
    return value

def phone_ambiguous(value):
    v=phone(value)
    return not bool(re.fullmatch(r'(?:\([2-9]\d{2}\) [2-9]\d{2}-\d{4}|\+\d{7,15})(?: ext\. \d+)?',v))

def url(value):
    value=str(value or '').strip()
    if value.lower().startswith('www.'):value='https://'+value
    try:
        p=urlsplit(value);host=(p.hostname or '').casefold()
        if host in ('linkedin.com','www.linkedin.com'):
            return urlunsplit(('https','www.linkedin.com',p.path.rstrip('/'),'',''))
    except ValueError:pass
    return value

def date_key(value):
    text=' '.join(str(value or '').casefold().split())
    text=re.sub(r'[–—]','-',text)
    text=re.sub(r'\b(current|now)\b','present',text)
    return re.sub(r'\b('+'|'.join(MONTHS)+r')\b',lambda m:str(MONTHS[m.group()]),text)

def normalized(field,value):
    if not isinstance(value,str):return value
    if field=='name':return personal_name(value)
    if field=='phone':return phone(value)
    if field in ('linkedin','website','github','project_url'):return url(value)
    return ' '.join(value.split())

def key(field,value):
    if not isinstance(value,str):return value
    value=normalized(field,value)
    if field in ('dates','start_date','end_date','expected_graduation'):return re.sub(r'\s*-\s*','-',date_key(value))
    if field in ('linkedin','website','github','project_url'):
        # URL paths outside LinkedIn may be case-sensitive.
        return value
    return value.casefold()

def same(field,a,b):return key(field,a)==key(field,b)

def repair_wrapped_links(text):
    # A trailing hyphen followed by a single URL token is a clear continuation;
    # never complete a truncated username from another document.
    return re.sub(r'((?:https?://|www\.)[^\s<>]+-)\s*\n\s*([a-zA-Z0-9_-]+/?)(?=\s*(?:\(LinkedIn\)|\n|$))',lambda m:m.group() if (not m.group(2)[0].islower() and not m.string[m.end():].lstrip().startswith('(LinkedIn)')) or m.group(2).rstrip('/').casefold() in {'experience','education','summary','skills','contact','certifications','projects','volunteering'} else m.group(1)+m.group(2),text,flags=re.I)
