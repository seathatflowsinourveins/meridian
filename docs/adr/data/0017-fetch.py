"""Fetch the audit pin anonymously into a new cache folder; never install globally."""
import hashlib, pathlib, tarfile, urllib.request
CACHE=pathlib.Path.home()/'.cache/meridian/adr-0017'
CACHE.mkdir(parents=True,exist_ok=False)
ARTIFACTS=[
 ('binary.tar.gz','https://github.com/rtk-ai/rtk/releases/download/v1.2.0/rtk-x86_64-unknown-linux-musl.tar.gz','70fee7b4a548c43dde94c77e2335550981b0bc2fb013691d8c8109b5bd0eda37','binary'),
 ('source.tar.gz','https://api.github.com/repos/rtk-ai/rtk/tarball/v1.2.0','bfe89c0f60e5bc8f0fd84180a79195915818b749ecd333cb6a9c45d275e2cfd5','source'),

]
TOKENIZER_PINS = {
    "o200k_base": "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d",
    "cl100k_base": "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7",
}
for encoding, digest in TOKENIZER_PINS.items():
 name = encoding + '.tiktoken'
 ARTIFACTS.append((name, 'https://openaipublic.blob.core.windows.net/encodings/' + name, digest, None))
for name,url,digest,directory in ARTIFACTS:
 data=urllib.request.urlopen(url).read()
 assert hashlib.sha256(data).hexdigest()==digest,name
 target=CACHE/name if directory else CACHE/'vocab'/name
 target.parent.mkdir(exist_ok=True);target.write_bytes(data)
 if directory:
  dest=CACHE/directory;dest.mkdir()
  with tarfile.open(target) as archive: archive.extractall(dest,filter='data')
print('Pinned artifacts verified; no init or PATH change performed.')
