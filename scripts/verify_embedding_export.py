"""Independent CPU export probe: standard library and pinned Sentence Transformers, no Django/registry/database."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--archive',required=True);parser.add_argument('--sha256',required=True)
    args=parser.parse_args();path=Path(args.archive)
    if not 1<=path.stat().st_size<=110*1024**2:raise ValueError('Unsupported archive size.')
    observed=hashlib.sha256(path.read_bytes()).hexdigest()
    if observed!=args.sha256:raise ValueError('Export checksum mismatch.')
    names={'model.safetensors','tokenizer_config.json','config.json','config_sentence_transformers.json',
        'tokenizer.json','sentence_bert_config.json','modules.json','2_Normalize/config.json','1_Pooling/config.json','LICENSE.txt','NOTICE.txt'}
    with tempfile.TemporaryDirectory(prefix='embedding-independent-') as folder:
        root=Path(folder)
        with zipfile.ZipFile(path) as archive:
            if set(archive.namelist())!=names or len(archive.namelist())!=len(names):raise ValueError('Unexpected export files.')
            for name in names:
                if archive.getinfo(name).file_size>100*1024**2:raise ValueError('Export member too large.')
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(name))
        modules=json.loads((root/'modules.json').read_text())
        allowed=['sentence_transformers.base.modules.transformer.Transformer',
            'sentence_transformers.sentence_transformer.modules.pooling.Pooling','sentence_transformers.base.modules.normalize.Normalize']
        if ([m.get('type') for m in modules]!=allowed or [m.get('path') for m in modules]!=['','1_Pooling','2_Normalize']):
            raise ValueError('Unexpected model module or path.')
        import numpy as np
        from sentence_transformers import SentenceTransformer
        model=SentenceTransformer(str(root),device='cpu',local_files_only=True,trust_remote_code=False,token=False)
        vectors=model.encode(['Independent embedding export load probe.'],normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False)
        if model.max_seq_length!=256 or vectors.shape!=(1,384) or not np.isfinite(vectors).all() or not np.allclose(np.linalg.norm(vectors,axis=1),1,atol=1e-5):
            raise ValueError('Invalid independent embedding output.')
        print(json.dumps({'export_sha256':observed,'dimension':384,'normalized':True,'device':'cpu',
            'probe_vector_sha256':hashlib.sha256(vectors.astype('<f4').tobytes()).hexdigest(),'registry_used':False}))


if __name__=='__main__':main()
