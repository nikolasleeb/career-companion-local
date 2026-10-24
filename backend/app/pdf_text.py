"""Conservative text-only repair of ligatures using an embedded TrueType glyph map.

No spell-checking or global quote/percent substitutions. The input PDF is never
written. Supported font tables: OpenType post 2 and Macintosh cmap 0/6.
https://learn.microsoft.com/en-us/typography/opentype/spec/post
https://learn.microsoft.com/en-us/typography/opentype/spec/cmap
"""
import re
import struct
from pypdf.generic import DecodedStreamObject,NameObject

LIGATURES={'fi':'fi','fl':'fl','ff':'ff','ffi':'ffi','ffl':'ffl','f_i':'fi','f_l':'fl','f_f':'ff','f_f_i':'ffi','f_f_l':'ffl','uniFB01':'fi','uniFB02':'fl','uniFB00':'ff','uniFB03':'ffi','uniFB04':'ffl'}

def glyph_ligatures(raw):
    """Return only byte codes backed by explicit custom glyph names."""
    if len(raw)>2*1024*1024 or len(raw)<12:return {}
    count=struct.unpack_from('>H',raw,4)[0]
    if count>100:return {}
    tables={}
    for i in range(count):
        tag,_,offset,length=struct.unpack_from('>4sIII',raw,12+16*i)
        if offset+length>len(raw):return {}
        tables[tag]=raw[offset:offset+length]
    post=tables.get(b'post',b'');cmap=tables.get(b'cmap',b'')
    if len(post)<34 or post[:4]!=b'\x00\x02\x00\x00' or len(cmap)<4:return {}
    num=struct.unpack_from('>H',post,32)[0]
    indices=struct.unpack_from('>'+str(num)+'H',post,34);pos=34+2*num;names=[]
    for _ in range(max(indices,default=257)-257):
        length=post[pos];pos+=1
        names.append(post[pos:pos+length].decode('ascii'));pos+=length
        if pos>len(post):return {}
    glyphs={i:LIGATURES[names[index-258].split('.')[0]] for i,index in enumerate(indices) if index>=258 and names[index-258].split('.')[0] in LIGATURES}
    subtables=struct.unpack_from('>H',cmap,2)[0]
    if subtables>100:return {}
    for i in range(subtables):
        platform,encoding,offset=struct.unpack_from('>HHI',cmap,4+8*i)
        if platform!=1 or encoding!=0:continue
        fmt=struct.unpack_from('>H',cmap,offset)[0]
        if fmt==0:
            codes={code:cmap[offset+6+code] for code in range(256)}
        elif fmt==6:
            start,num=struct.unpack_from('>HH',cmap,offset+6)
            if start+num>256:continue
            codes={start+j:struct.unpack_from('>H',cmap,offset+10+2*j)[0] for j in range(num)}
        else:continue
        return {code:glyphs[gid] for code,gid in codes.items() if gid in glyphs}
    return {}


def repair_ligatures(reader):
    repaired=0;seen=set()
    for page in reader.pages:
        resources=page.get('/Resources',{})
        if hasattr(resources,'get_object'):resources=resources.get_object()
        if not hasattr(resources,'get'):continue
        fonts=resources.get('/Font',{})
        if hasattr(fonts,'get_object'):fonts=fonts.get_object()
        if not hasattr(fonts,'values'):continue
        for ref in fonts.values():
            font=ref.get_object()
            if id(font) in seen:continue
            seen.add(id(font))
            try:
                if font.get('/Subtype')!='/TrueType' or font.get('/ToUnicode') is None:continue
                descriptor=font.get('/FontDescriptor')
                if not descriptor:continue
                embedded=descriptor.get_object().get('/FontFile2')
                if embedded is None:continue
                changes=glyph_ligatures(embedded.get_object().get_data())
                if not changes:continue
                original=font['/ToUnicode'].get_data().decode('latin1')
                # Only single-byte source encodings and single-code mappings are
                # repaired. Unrecognized ranges/arrays stay untouched.
                if not re.search(r'<00>\s*<FF>',original,re.I):continue
                edits=0
                def ranges(m):
                    nonlocal edits
                    start,end=int(m[1],16),int(m[2],16)
                    if start!=end or start not in changes:return m[0]
                    value=changes[start].encode('utf-16-be').hex()
                    if value.casefold()==m[3].casefold():return m[0]
                    edits+=1;return '<'+m[1]+'><'+m[2]+'><'+value+'>'
                def chars(m):
                    nonlocal edits
                    code=int(m[1],16)
                    if code not in changes:return m[0]
                    value=changes[code].encode('utf-16-be').hex()
                    if value.casefold()==m[2].casefold():return m[0]
                    edits+=1;return '<'+m[1]+'><'+value+'>'
                value=re.sub(r'beginbfrange(.*?)endbfrange',lambda block:'beginbfrange'+re.sub(r'<([0-9A-Fa-f]{2})>\s*<([0-9A-Fa-f]{2})>\s*<([0-9A-Fa-f]+)>',ranges,block[1])+'endbfrange',original,flags=re.S)
                value=re.sub(r'beginbfchar(.*?)endbfchar',lambda block:'beginbfchar'+re.sub(r'<([0-9A-Fa-f]{2})>\s*<([0-9A-Fa-f]+)>',chars,block[1])+'endbfchar',value,flags=re.S)
                if edits:
                    stream=DecodedStreamObject();stream.set_data(value.encode('latin1'));font[NameObject('/ToUnicode')]=stream;repaired+=edits
            except Exception:
                continue  # Unsupported/damaged fonts retain the normal PDF extraction.
    return repaired
