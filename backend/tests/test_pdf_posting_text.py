import io
import struct
from types import SimpleNamespace
import pytest
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
from reportlab.pdfgen import canvas
from app import documents,job_parser,pdf_text


def embedded_font(format=6,names=('f_i','f_l','percent')):
    # Minimal OpenType post/cmap tables: explicit glyph names are the evidence,
    # not an English-word replacement list.
    post=struct.pack('>I',0x00020000)+bytes(28)+struct.pack('>H4H',4,0,258,259,260)
    post+=b''.join(bytes([len(n)])+n.encode('ascii') for n in names)
    if format==6:sub=struct.pack('>HHHHH5H',6,20,0,34,5,1,0,0,2,3)
    else:
        codes=bytearray(256);codes[34]=1;codes[37]=2;codes[38]=3
        sub=struct.pack('>HHH',0,262,0)+bytes(codes)
    cmap=struct.pack('>HHHHI',0,1,1,0,12)+sub
    header=struct.pack('>IHHHH',0x00010000,2,0,0,0)
    directory=struct.pack('>4sIII',b'post',0,44,len(post))+struct.pack('>4sIII',b'cmap',0,44+len(post),len(cmap))
    return header+directory+post+cmap


@pytest.mark.parametrize('format',[0,6])
def test_only_font_named_ligatures_supply_repairs(format):
    assert pdf_text.glyph_ligatures(embedded_font(format))=={34:'fi',37:'fl'}
    assert pdf_text.glyph_ligatures(embedded_font(format,('quotedbl','percent','ampersand')))=={}


@pytest.mark.parametrize('raw',[b'broken',bytes(12)])
def test_unsupported_font_data_is_not_guessed(raw):
    assert pdf_text.glyph_ligatures(raw)=={}


@pytest.mark.parametrize('kind',['bfrange','bfchar'])
def test_repair_is_font_scoped_and_preserves_other_punctuation(kind):
    def stream(raw):
        s=DecodedStreamObject();s.set_data(raw);return s
    rows='<22><22><0022>\n<25><25><0025>\n<26><26><0025>' if kind=='bfrange' else '<22><0022>\n<25><0025>\n<26><0025>'
    original=('begincmap\n1 begincodespacerange\n<00><FF>\nendcodespacerange\n3 begin'+kind+'\n'+rows+'\nend'+kind+'\nendcmap').encode()
    font=DictionaryObject({NameObject('/Subtype'):NameObject('/TrueType'),NameObject('/ToUnicode'):stream(original),NameObject('/FontDescriptor'):DictionaryObject({NameObject('/FontFile2'):stream(embedded_font())})})
    ordinary=DictionaryObject({NameObject('/Subtype'):NameObject('/Type1'),NameObject('/ToUnicode'):stream(original)})
    page=DictionaryObject({NameObject('/Resources'):DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/Broken'):font,NameObject('/Normal'):ordinary})})})
    reader=SimpleNamespace(pages=[page,page])
    assert pdf_text.repair_ligatures(reader)==2
    repaired=font['/ToUnicode'].get_data()
    assert b'<00660069>' in repaired and b'<0066006c>' in repaired
    assert (b'<26><26><0025>' if kind=='bfrange' else b'<26><0025>') in repaired
    assert ordinary['/ToUnicode'].get_data()==original
    assert pdf_text.repair_ligatures(reader)==0


def test_normal_quotes_percentages_and_profile_extraction_unchanged():
    buf=io.BytesIO();pdf=canvas.Canvas(buf);pdf.drawString(40,700,'Revenue grew 25%. The report said "verified".');pdf.save();raw=buf.getvalue()
    normal=documents.extract('source.pdf',raw)
    repaired=documents.extract('posting.pdf',raw,repair_font_mappings=True)
    assert repaired['text']==normal['text'] and '25%' in repaired['text'] and '"verified"' in repaired['text']


def test_page_headers_join_continuations_without_joining_separate_bullets():
    text='''Role Overview:
You will tackle exciting
On this page: Job Description Benefits How to Apply

10/8/26, 2:14 PMExample Careers
Page 3 of 8https://example.com/jobs/1
challenges in machine learning and build useful tools.
What you’ll be doing:
• Build models.
• Explain findings.
Who we’re looking for:
• A willingness to work flexibly and

10/8/26, 2:14 PMExample Careers
Page 4 of 8https://example.com/jobs/1
travel between sites.
• An open-minded approach to work.
Minimum GPA: 3.0
'''
    value=job_parser.organize({'title':'ML Engineer','description':text})
    assert value['summary']==['You will tackle exciting challenges in machine learning and build useful tools.']
    assert len(value['sections']['other'])==2 and 'flexibly and travel between sites.' in value['sections']['other'][0]['text']
    assert len(value['sections']['responsibilities'])==2 and len(value['sections']['required'])==1
    for group in value['sections'].values():
        for row in group:assert row['source'] in text and 'Page' not in row['text']


def test_until_filled_deadline_is_a_fact_without_inventing_a_date():
    raw='Accepting applications until filled\nLocation: Indianapolis, IN\nRequirements\nMinimum GPA: 3.0'
    value=job_parser.organize({'title':'ML Engineer','description':raw})
    assert value['facts']['deadline']['value']=='Until filled'
    assert value['facts']['deadline']['sources']==['Accepting applications until filled']
