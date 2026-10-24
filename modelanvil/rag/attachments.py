"""Qualified document extraction and current artifact provenance for research corpora."""
import hashlib
import json
import zipfile
from xml.etree import ElementTree
from pathlib import Path
from modelanvil.data.source_import import extract_source
from modelanvil.runners.inference import verified_artifact
from modelanvil.runners.training.runtime import digest

TEXT_EXTENSIONS={'.txt','.md','.py','.js','.ts','.tsx','.jsx','.json','.csv','.rs','.go','.java','.c','.cpp','.h','.css','.html','.sql','.sh','.yaml','.yml'}

def extract(raw,name):
    if not isinstance(raw,bytes) or not 0<len(raw)<=1024**2:raise ValueError('Attach at most1MiB per document.')
    suffix=Path(name).suffix.lower()
    if suffix in ('.pdf','.docx'):
        try:rows=extract_source(raw,source_format=suffix[1:])
        except (KeyError,zipfile.BadZipFile,ElementTree.ParseError,UnicodeDecodeError):
            raise ValueError('Document extraction refused malformed PDF/DOCX content. Attach a readable supported text document.') from None
        text='\n\n'.join(row['blocks'][0]['text'] for row in rows)
        locations=[];offset=0
        for row in rows:
            block=row['blocks'][0];locations.append({'start':offset,'end':offset+len(block['text']),**block['location']});offset+=len(block['text'])+2
        parser=rows[0]['provenance']['transformation_revision_ref']
    elif suffix in TEXT_EXTENSIONS:
        try:text=raw.decode('utf-8-sig')
        except UnicodeDecodeError:raise ValueError('Code/text attachments require UTF-8.') from None
        if '\x00' in text or not text.strip():raise ValueError('Attach nonempty UTF-8 text without null bytes.')
        locations=[{'start':0,'end':len(text),'source_path':'text'}];parser='modelanvil.utf8-source.v1'
    else:raise ValueError('Attach PDF/DOCX or UTF-8 code/text. Images require a completed qualified OCR job. Audio needs a separately qualified transcription path and is unavailable here.')
    if len(text.encode())>500000:raise ValueError('Extracted text exceeds500,000 UTF-8 bytes.')
    if len(locations)>256 or len(json.dumps(locations).encode())>32768:
        raise ValueError('Document location metadata exceeds256 records or32KiB; attach a smaller document.')
    return text,{'source_sha256':hashlib.sha256(raw).hexdigest(),'extraction':parser,'locations':locations}


def ocr(record):
    from modelanvil.runners import specialist_jobs,specialists
    from modelanvil.identity.models import check_resource_access
    if (record.status!='completed' or record.configuration.get('kind')!='ocr' or not check_resource_access(record)
            or record.model_version.state!='qualified'):
        raise ValueError('Select a completed qualified OCR job in this project.')
    frozen=record.configuration.get('frozen',{})
    if frozen.get('runtime')!=specialist_jobs.runtime_digest():raise ValueError('OCR execution requires current qualified runtime evidence.')
    specialists.snapshot(record.model_version,record.tenant_id,record.project_id,'ocr')
    refs=[frozen.get('image'),frozen.get('snapshot'),record.configuration.get('result')]
    if any(not x for x in refs):raise ValueError('This OCR job lacks durable pinned provenance.')
    for ref in refs:verified_artifact(ref,record.tenant_id,record.project_id)
    result=specialist_jobs.read_result(record)
    if digest(result)!=record.output_digest:raise ValueError('OCR result digest changed.')
    pages=result.get('pages',[{'page':1,'text':result.get('text','')}])
    text='\n\n'.join(p['text'] for p in pages)
    if not text.strip() or len(text.encode())>500000:raise ValueError('OCR text is empty or exceeds the attachment limit.')
    if frozen.get('layout_snapshot'):refs.append(frozen['layout_snapshot'])
    return text,{'extraction':'modelanvil.qualified-ocr-result.v1','source_sha256':refs[0]['sha256'],
        'source_artifacts':refs,'ocr_request_id':str(record.request_id),'ocr_output_digest':record.output_digest,
        'ocr_model_id':str(record.model_version.model_version_id),
        'locations':[{'page':p['page'],'text_sha256':hashlib.sha256(p['text'].encode()).hexdigest()} for p in pages],
        'review_required':True}


def unavailable_documents(base,tenant,project):
    from modelanvil.rag.models import SourceDocument
    bad=[]
    for document in SourceDocument.all_objects.filter(knowledge_base_id=base,tenant_id=tenant,metadata__source_artifacts__isnull=False):
        try:
            refs=document.metadata['source_artifacts']
            if not isinstance(refs,list) or not 1<=len(refs)<=4:raise ValueError()
            for ref in refs:verified_artifact(ref,tenant,project)
            if document.metadata.get('ocr_model_id'):
                from modelanvil.runners.models import ModelVersion
                from modelanvil.identity.models import check_resource_access
                model=ModelVersion.all_objects.filter(tenant_id=tenant,model_version_id=document.metadata['ocr_model_id'],state='qualified').first()
                if not check_resource_access(model,project,tenant):raise ValueError()
        except (ValueError,KeyError,TypeError):bad.append(document.pk)
    return bad
