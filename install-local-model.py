"""Install the pinned Hugging Face model and official llama.cpp CPU runtime locally."""
from pathlib import Path
import hashlib, json, zipfile
import httpx
ROOT=Path(__file__).resolve().parent
TARGET=ROOT/'data'/'local-model'
MODEL='Qwen3.5-4B-Q4_K_M.gguf'
MODEL_SHA='25082a7dd3776cc3c741c6347d3bd04523f05796607b3fbc32fa3a25dfa1418c'
REVISION='f9f88ac3e234be915e23811a6d28ea287bdb927e'
RUNTIME_SHA='a23e548c6b3525c38bcfeceaff919786ae06741857043cb670279b70100e5483'
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''): h.update(block)
    return h.hexdigest()
def download(url,path,sha):
    if path.exists() and digest(path)==sha:
        print('Already verified:',path.name,flush=True);return
    partial=path.with_suffix(path.suffix+'.part')
    with httpx.Client(follow_redirects=True,timeout=120) as client, client.stream('GET',url) as response:
        response.raise_for_status();total=int(response.headers.get('content-length',0));done=0;last=0
        with partial.open('wb') as out:
            for block in response.iter_bytes(1024*1024):
                out.write(block);done+=len(block)
                if done-last>=100*1024*1024:
                    print(f'{path.name}: {done//1024//1024} MB / {total//1024//1024} MB',flush=True);last=done
    if digest(partial)!=sha: raise RuntimeError('Checksum mismatch: '+path.name)
    partial.replace(path);print('Verified:',path.name,flush=True)
if __name__=='__main__':
    TARGET.mkdir(parents=True,exist_ok=True)
    archive=TARGET/'llama-b11476-bin-win-cpu-x64.zip'
    download('https://github.com/ggml-org/llama.cpp/releases/download/b11476/'+archive.name,archive,RUNTIME_SHA)
    runtime=TARGET/'runtime';runtime.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            destination=(runtime/item.filename).resolve()
            if not destination.is_relative_to(runtime.resolve()): raise RuntimeError('Unsafe archive path')
        z.extractall(runtime)
    download('https://huggingface.co/lmstudio-community/Qwen3.5-4B-GGUF/resolve/'+REVISION+'/'+MODEL,TARGET/MODEL,MODEL_SHA)
    (TARGET/'manifest.json').write_text(json.dumps({'model':MODEL,'model_sha256':MODEL_SHA,'revision':REVISION,'runtime':'b11476','runtime_sha256':RUNTIME_SHA},indent=2),encoding='utf-8')
    print('Local model installed. Equity Scout starts it automatically.',flush=True)
