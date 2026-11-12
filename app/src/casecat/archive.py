"""Immutable ZIP assets and atomic, validated export."""
from dataclasses import dataclass
from copy import copy
from functools import cached_property
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import unicodedata
import zipfile
import zlib


MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_EXPANDED_BYTES = 8 * 1024**3
MAX_MEMBERS = 10000


def safe_member(name):
    parts = name.rstrip('/').split('/')
    reserved = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', re.I)
    if (not name or '\\' in name or name.startswith('/')
            or any(not p or p in ('.', '..') or p.endswith((' ', '.')) or reserved.match(p)
                   or any(ord(c) < 32 or c in ':<>"|?*' for c in p) for p in parts)):
        raise ValueError(f'Unsafe archive member: {name!r}')
    return unicodedata.normalize('NFC', '/'.join(parts)).casefold()


@dataclass(frozen=True)
class Archive:
    data: bytes
    name: str
    source_path: str | None
    members: tuple[str, ...]
    jobs: tuple[str, ...]

    @cached_property
    def digest(self):
        return hashlib.sha256(self.data).hexdigest()

    @property
    def export_name(self):
        stem = re.sub(r'(?:_AI)+$', '', Path(self.name).stem, flags=re.I)
        return f'{stem}_AI.zip'

    def member(self, requested):
        return next((name for name in self.members if name.casefold() == requested.casefold()), None)

    def read(self, name):
        with zipfile.ZipFile(io.BytesIO(self.data)) as source:
            return source.read(name)


def inspect_archive(source, *, name='CaseCAT.zip', source_path=None):
    if not isinstance(source, bytes):
        path = Path(source).resolve()
        if path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError('CaseCAT archive exceeds the 2 GB import limit.')
        source, name, source_path = path.read_bytes(), path.name, str(path)
    if len(source) > MAX_ARCHIVE_BYTES:
        raise ValueError('CaseCAT archive exceeds the 2 GB import limit.')
    try:
        with zipfile.ZipFile(io.BytesIO(source)) as z:
            infos = z.infolist()
            if len(infos) > MAX_MEMBERS or sum(i.file_size for i in infos) > MAX_EXPANDED_BYTES:
                raise ValueError('CaseCAT archive exceeds the extraction limits.')
            seen = set()
            for info in infos:
                key = safe_member(info.orig_filename)
                if key in seen:
                    raise ValueError('Duplicate or ambiguous archive member.')
                seen.add(key)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode) or info.flag_bits & 1:
                    raise ValueError('Links and encrypted archive members are unsupported.')
                # Check CRCs before the active document can be changed.
                with z.open(info) as stream:
                    while stream.read(1024 * 1024):
                        pass
            names = tuple(i.filename for i in infos)
            jobs = tuple(name[:-6] for name in names if name.lower().endswith('.sgngl'))
            if not jobs:
                raise ValueError('No CaseCAT transcript (.sgngl) was found in this ZIP.')
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, zlib.error, EOFError) as exc:
        raise ValueError(f'Invalid or unsupported CaseCAT ZIP: {exc}') from exc
    return Archive(source, Path(name).name, source_path, names, jobs)


def atomic_publish(target, data, *, overwrite=False):
    """Publish only complete, flushed bytes. Failed writes preserve destinations."""
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.bababui-', suffix='.tmp', dir=target.parent)
    try:
        with os.fdopen(handle, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        if overwrite:
            os.replace(temporary, target)
        else:
            try:
                os.link(temporary, target)
            except FileExistsError as exc:
                raise ValueError('That destination already exists.') from exc
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def materialize_audio(bundle, job, directory):
    if job.audio_member is None:
        return None
    data = bundle.read(job.audio_member)
    # Never use an archive member as a filesystem path.
    key = hashlib.sha256(job.audio_member.encode()).hexdigest()[:20]
    target = Path(directory) / bundle.digest / f'{key}.wav'
    if not target.exists() or target.read_bytes() != data:
        atomic_publish(target, data, overwrite=True)
    return target


def export_zip(bundle, job, target, *, overwrite=False):
    from .codec import validate_job, serialize_native, load_job
    target = Path(target).resolve()
    if target.suffix.lower() != '.zip':
        raise ValueError('Export with a .zip extension.')
    if bundle.source_path:
        source = Path(bundle.source_path).resolve()
        if target == source or (target.exists() and source.exists() and os.path.samefile(target, source)):
            raise ValueError('The imported source archive is protected. Choose another destination.')
    validate_job(bundle, job)
    if target.exists() and not overwrite:
        raise ValueError('That destination already exists.')
    serialized = serialize_native(job, bundle)
    from .fields import serialize_metadata
    metadata = serialize_metadata(job, bundle)
    data = bundle.data
    metadata_member = bundle.member(job.key + '.sgxml')
    changed = {}
    if serialized != job.native_bytes:
        changed[bundle.member(job.key + '.sgngl')] = serialized
    if metadata_member and metadata != bundle.read(metadata_member):
        changed[metadata_member] = metadata
    if changed:
        buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(bundle.data)) as source, zipfile.ZipFile(buffer, 'w') as output:
            output.comment = source.comment
            for info in source.infolist():
                payload = changed.get(info.filename, source.read(info))
                output.writestr(copy(info), payload)
        data = buffer.getvalue()
        checked = inspect_archive(data, name=bundle.export_name)
        restored = load_job(checked, job.key)
        if restored.text != job.text or restored.notes_bytes != job.notes_bytes:
            raise ValueError('Export validation found changed text or original steno.')
        # Validate all companion jobs, dictionaries, audio and opaque payloads,
        # including their names. No companion metadata is rewritten speculatively.
        if checked.members != bundle.members or any(
                checked.read(name) != bundle.read(name)
                for name in bundle.members if name not in changed and not name.endswith('/')):
            raise ValueError('Export validation found a changed companion asset.')
    # Baseline export preserves compression, ZIP headers, timestamps and comments.
    # All bytes were validated at import and the immutable source is unchanged.
    atomic_publish(target, data, overwrite=overwrite)
