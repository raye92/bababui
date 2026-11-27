"""Self-contained working projects, distinct from native CaseCAT exports."""
from dataclasses import dataclass, replace
from functools import cached_property
import hashlib
import io
import json
from pathlib import Path
import zipfile
import zlib

from . import archive, codec
from .anchors import Revision
from .caption import cover_bounds
from app.src.speech_alignment import SpeechAlignment
from app.src.notice_model import NoticeDetails


# Only fingerprints live here, never archive bytes. Recovery loading still
# verifies the archive checksum independently of this process-local cache.
_verified_recovery_assets = {}


def _asset_fingerprint(target):
    try:
        value = target.stat()
    except FileNotFoundError:
        return None
    return (value.st_dev, value.st_ino, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


@dataclass(frozen=True)
class AttachedNotice:
    filename: str
    pdf: bytes
    details: NoticeDetails
    native_bytes: bytes
    xml_bytes: bytes | None
    body_start: int

    @cached_property
    def data(self):
        out = io.BytesIO()
        meta = {'filename': self.filename, 'details': self.details.to_dict(), 'body_start': self.body_start}
        members = {'notice.pdf': self.pdf, 'cover.sgngl': self.native_bytes,
                   'notice.json': json.dumps(meta, ensure_ascii=False).encode('utf-8')}
        if self.xml_bytes is not None:
            members['cover.sgxml'] = self.xml_bytes
        with zipfile.ZipFile(out, 'w') as result:
            for name, data in members.items():
                result.writestr(zipfile.ZipInfo(name), data, compress_type=zipfile.ZIP_DEFLATED)
        return out.getvalue()

    @cached_property
    def digest(self):
        return hashlib.sha256(self.data).hexdigest()

    @classmethod
    def unpack(cls, data, digest):
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('The saved notice checksum does not match.')
        with zipfile.ZipFile(io.BytesIO(data)) as parts:
            names = sorted(parts.namelist())
            if names not in (['cover.sgngl', 'notice.json', 'notice.pdf'],
                             ['cover.sgngl', 'cover.sgxml', 'notice.json', 'notice.pdf']):
                raise ValueError('Invalid saved notice members.')
            if sum(i.file_size for i in parts.infolist()) > archive.MAX_ARCHIVE_BYTES:
                raise ValueError('Saved notice is too large.')
            meta = json.loads(parts.read('notice.json'))
            if not isinstance(meta['filename'], str) or type(meta['body_start']) is not int:
                raise ValueError('Invalid saved notice metadata.')
            result = cls(meta['filename'], parts.read('notice.pdf'), NoticeDetails.from_dict(meta['details']),
                         parts.read('cover.sgngl'), parts.read('cover.sgxml') if 'cover.sgxml' in names else None,
                         meta['body_start'])
            result.__dict__.update(data=data, digest=digest)
            return result


@dataclass
class NativeState:
    bundle: archive.Archive
    job: codec.NativeJob
    original: Revision
    incoming: Revision
    review: dict | None = None
    alignment: SpeechAlignment | None = None
    notice: AttachedNotice | None = None

    @classmethod
    def load(cls, bundle, key):
        job = codec.load_job(bundle, key)
        return cls(bundle, job, job.revision, job.revision)

    def duplicate(self):
        from copy import deepcopy
        return replace(self, review=deepcopy(self.review))

    @cached_property
    def recording(self):
        from app.src.notice_model import recording_details
        if not self.bundle.overrides:
            return recording_details(self.bundle, self.job)
        source = replace(self.bundle, overrides=())
        return recording_details(source, codec.load_job(source, self.job.key))

    @cached_property
    def source_body_start(self):
        from .cover import existing_cover
        try:
            return existing_cover(self.bundle, self.job)[2]
        except ValueError:
            # A reporter may have edited the standard closing declaration in
            # Case CATalyst. Only accept an identifiable testimony heading.
            import re
            text = self.job.baseline.text
            index = text.find('I N D E X')
            oath = text.lower().find('examined and testified as follows', max(0, index))
            if index >= 0 and oath >= 0:
                heading = re.search(r'(?im)^[ \t]*(?:(?:DIRECT|CROSS|REDIRECT|RECROSS)[ -])?EXAMINATION[ \t]*$',
                                    text[oath:])
                if heading:
                    return oath + heading.start()
            raise ValueError('Could not identify the first line of testimony in this cover.')

    def body_position(self, revision):
        start = self.notice.body_start if self.notice else self.source_body_start
        if not start:
            return 0
        if revision.text.startswith(self.job.baseline.text[:start]):
            return start
        from app.src.review_model import map_position
        from app.src.suggestions import text_edits
        return map_position(start, text_edits(self.job.baseline.text, revision.text))

    def edited_job(self, revision):
        if revision == self.job.baseline:
            return self.bundle, self.job
        from .fields import serialize_metadata
        job = self.job.with_revision(revision)
        bundle = self.bundle.with_job_bytes(job.key, codec.serialize_native(job, self.bundle),
                                            serialize_metadata(job, self.bundle))
        return bundle, codec.load_job(bundle, job.key)

    def with_notice(self, filename, pdf, details, index_pages):
        from .cover import build_cover
        from app.src.notice_review import remap_review
        from app.src.review_model import map_position
        from app.src.suggestions import text_edits

        def covered(revision):
            bundle, source = self.edited_job(revision)
            native, xml, old_start, start = build_cover(bundle, source, details, index_pages=index_pages)
            overlay = bundle.with_job_bytes(source.key, native, xml)
            job = codec.load_job(overlay, source.key)
            if not 0 <= start <= len(job.text) or not 0 <= old_start <= len(source.text):
                raise ValueError('Could not locate the start of testimony.')
            edits = text_edits(source.text[old_start:], job.text[start:]) if self.review else ()
            def mapped(p):
                return start + map_position(max(0, p-old_start), edits)
            return overlay, job, start, mapped

        bundle, job, start, original_map = covered(self.original)
        incoming, incoming_map = job.baseline, original_map
        if self.incoming != self.original:
            _, proposed, _, incoming_map = covered(self.incoming)
            incoming = _revision_on_baseline(job.baseline, proposed.baseline)
        xml = bundle.member(job.key + '.sgxml')
        notice = AttachedNotice(Path(filename).name, pdf, details, job.native_bytes, bundle.read(xml) if xml else None, start)
        result = replace(self, bundle=bundle, job=job, original=job.baseline, incoming=incoming,
                         review=remap_review(self.review, original_map, incoming_map), notice=notice)
        codec.validate_job(bundle, job.with_revision(incoming))
        if result.review:
            from app.src.suggestion_filter import validate_review
            validate_review(result.review, incoming.text)
        return result

    def to_dict(self):
        return {**({'notice_sha256': self.notice.digest} if self.notice else {}),
                'job': self.job.key, 'source_sha256': self.bundle.digest,
                'source_name': self.bundle.name, 'source_path': self.bundle.source_path,
                'original': self.original.to_dict(), 'incoming': self.incoming.to_dict(),
                'review': self.review, 'alignment': vars(self.alignment).copy() if self.alignment else None,
                'text_projection_version': codec.TEXT_PROJECTION_VERSION}

    @classmethod
    def restore(cls, bundle, record, notice=None):
        try:
            if (not isinstance(record, dict) or not isinstance(record.get('job'), str)
                    or not isinstance(record.get('source_name'), str)
                    or (record.get('source_path') is not None and not isinstance(record['source_path'], str))):
                raise ValueError('Invalid native project metadata.')
            if bundle.digest != record['source_sha256']:
                raise ValueError('The original archive checksum does not match.')
            if record.get('notice_sha256') != (notice.digest if notice else None):
                raise ValueError('The saved notice is missing or does not match.')
            if notice:
                bundle = bundle.with_job_bytes(record['job'], notice.native_bytes, notice.xml_bytes)
            state = cls.load(bundle, record['job'])
            state.notice = notice
            version = record.get('text_projection_version', 1)
            if type(version) is not int or not 1 <= version <= codec.TEXT_PROJECTION_VERSION:
                raise ValueError('Unsupported native text projection version.')
            state.original = Revision.from_dict(record['original'])
            state.incoming = Revision.from_dict(record['incoming'])
            # Saved ranges use the editor text the reviewer originally saw.
            saved_job = state.job
            if version == 1:
                saved_job = codec.load_job(bundle, record['job'], projection_version=version)
            elif version == 2:
                bounds = cover_bounds(saved_job.native_bytes)
                # Projects that already displayed the table recorded its wrapped
                # party fields, including when the final blank had been edited.
                known_table = bounds[1] and any(e.wrap_caption for rev in (state.original, state.incoming)
                                                for e in rev.elements if e.source is not None)
                if not known_table and bounds != cover_bounds(saved_job.native_bytes, legacy=True):
                    saved_job = codec.load_job(bundle, record['job'], projection_version=version)
            if notice and not 0 <= notice.body_start <= len(saved_job.text):
                raise ValueError('Invalid saved start of testimony.')
            state.review = record.get('review')
            state.alignment = SpeechAlignment.restore(record.get('alignment'), len(state.job.stroke_clocks))
            if state.review is not None:
                from app.src.suggestion_filter import validate_review
                validate_review(state.review, state.incoming.text)
            for side in ('original', 'incoming'):
                if 'definitions' not in record[side]:
                    from .fields import field_values
                    values = dict(saved_job.baseline.definitions)
                    values.update(field_values(getattr(state, side)))
                    setattr(state, side, replace(getattr(state, side), definitions=tuple(sorted(values.items()))))
                if 'all_caps' not in record[side]:
                    setattr(state, side, replace(getattr(state, side), all_caps=saved_job.baseline.all_caps))
                if 'elements' not in record[side]:
                    revision = getattr(state, side)
                    restored = saved_job.baseline._replace(0, len(saved_job.text), revision.text)
                    setattr(state, side, replace(revision, elements=restored.elements))
            codec.validate_job(bundle, saved_job.with_revision(state.original))
            codec.validate_job(bundle, saved_job.with_revision(state.incoming))
            if state.review and 'pending_decisions' in state.review:
                from app.src.review_editing import restore_decisions
                restore_decisions(state.original, state.incoming, state.review['pending_decisions'])
            if saved_job.baseline != state.job.baseline:
                from .project_tabs import projection_changes, restore_controls, restore_control_review
                groups, formats = projection_changes(saved_job, state.job, bundle, version)
                if groups or formats:
                    original, original_map = restore_controls(saved_job, state.original, groups, formats)
                    incoming, incoming_map = ((original, original_map) if state.original == state.incoming
                                             else restore_controls(saved_job, state.incoming, groups, formats))
                    if state.original == saved_job.baseline and original.text == state.job.text:
                        original = state.job.baseline
                    if state.incoming == saved_job.baseline and incoming.text == state.job.text:
                        incoming = state.job.baseline
                    state.review = restore_control_review(state.review, original, incoming, original_map, incoming_map)
                    state.original, state.incoming = original, incoming
                    if notice:
                        _, baseline_map = restore_controls(saved_job, saved_job.baseline, groups, formats)
                        body_start = baseline_map(notice.body_start, before=True)
                        if body_start != notice.body_start:
                            state.notice = replace(notice, body_start=body_start)
                    if state.review and 'pending_decisions' in state.review:
                        restore_decisions(state.original, state.incoming, state.review['pending_decisions'])
                codec.validate_job(bundle, state.job.with_revision(state.original))
                codec.validate_job(bundle, state.job.with_revision(state.incoming))
            return state
        except (KeyError, TypeError) as exc:
            raise ValueError('Invalid native working project.') from exc


def project_bytes(state, document):
    out = io.BytesIO()
    record = {'version': 3 if state.notice else 2, 'native': state.to_dict(), 'document': document}
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as result:
        result.writestr('source.zip', state.bundle.data, compress_type=zipfile.ZIP_STORED)
        if state.notice:
            result.writestr('notice.zip', state.notice.data, compress_type=zipfile.ZIP_STORED)
        result.writestr('document.json', json.dumps(record, ensure_ascii=False).encode('utf-8'))
    data = out.getvalue()
    # Verify the exact candidate before the existing working project is replaced.
    read_project(data)
    return data


def without_legacy_text(document, native):
    """Check redundant document text against the saved revision projection."""
    if (not native or not isinstance(document, dict)
            or native.get('text_projection_version', 1) >= codec.TEXT_PROJECTION_VERSION
            or not {'original', 'incoming'}.intersection(document)):
        return document
    document = dict(document)
    for side in ('original', 'incoming'):
        if side in document:
            text = ''.join(span['content'] for span in native[side]['spans'])
            if document.pop(side) != text:
                raise ValueError('Legacy text disagrees with the structured revision.')
    return document


def read_project(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as project:
            members = sorted(project.namelist())
            if members not in (['document.json', 'source.zip'], ['document.json', 'notice.zip', 'source.zip']):
                raise ValueError('Invalid working project members.')
            if (project.getinfo('source.zip').file_size > archive.MAX_ARCHIVE_BYTES
                    or project.getinfo('document.json').file_size > 64 * 1024**2):
                raise ValueError('Working project exceeds the supported size limits.')
            record = json.loads(project.read('document.json'))
            if record['version'] not in (1, 2, 3) or ('notice.zip' in members) != (record['version'] == 3):
                raise ValueError('Unsupported working project version.')
            native = record['native']
            if (not isinstance(native, dict) or not isinstance(native.get('source_name'), str)
                    or (native.get('source_path') is not None and not isinstance(native['source_path'], str))):
                raise ValueError('Invalid native project metadata.')
            bundle = archive.inspect_archive(project.read('source.zip'), name=native['source_name'],
                                             source_path=native.get('source_path'))
            notice = None
            if 'notice.zip' in members:
                if project.getinfo('notice.zip').file_size > archive.MAX_ARCHIVE_BYTES:
                    raise ValueError('Saved notice is too large.')
                notice = AttachedNotice.unpack(project.read('notice.zip'), native['notice_sha256'])
            state = NativeState.restore(bundle, native, notice)
            return state, without_legacy_text(record['document'], native)
    except (zipfile.BadZipFile, KeyError, TypeError, UnicodeError, RuntimeError, zlib.error, EOFError) as exc:
        raise ValueError('Invalid native working project.') from exc


def recovery_asset(path, state):
    directory = Path(str(path) + '.assets')
    _publish_asset(directory, state.bundle.digest, '.zip', state.bundle.data)
    if state.notice:
        _publish_asset(directory, state.notice.digest, '.notice', state.notice.data)


def _publish_asset(directory, digest, suffix, data):
    target = (directory / f'{digest}{suffix}').resolve()
    before = _asset_fingerprint(target)
    if before is not None and _verified_recovery_assets.get(target) == (digest, before):
        return
    if before is None or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        archive.atomic_publish(target, data, overwrite=True)
        before = _asset_fingerprint(target)
    after = _asset_fingerprint(target)
    if before is not None and before == after:
        # Bound the cache without retaining closed documents or their audio.
        if target not in _verified_recovery_assets and len(_verified_recovery_assets) >= 256:
            _verified_recovery_assets.pop(next(iter(_verified_recovery_assets)))
        _verified_recovery_assets[target] = (digest, after)


def recover_state(path, record, bundles):
    digest = record['source_sha256']
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Invalid recovery asset identifier.')
    key = (digest, record['source_name'], record.get('source_path'))
    if key not in bundles:
        source = Path(str(path) + '.assets') / f'{digest}.zip'
        bundles[key] = archive.inspect_archive(source.read_bytes(), name=record['source_name'],
                                              source_path=record.get('source_path'))
    notice = None
    if 'notice_sha256' in record:
        notice_id = record['notice_sha256']
        if not isinstance(notice_id, str) or len(notice_id) != 64 or any(c not in '0123456789abcdef' for c in notice_id):
            raise ValueError('Invalid recovery notice identifier.')
        if notice_id not in bundles:
            data = (Path(str(path) + '.assets') / f'{notice_id}.notice').read_bytes()
            bundles[notice_id] = AttachedNotice.unpack(data, notice_id)
        notice = bundles[notice_id]
    return NativeState.restore(bundles[key], record, notice)


def _revision_on_baseline(baseline, proposed):
    """Keep each proposed passage at its physical steno group in the new cover."""
    if baseline == proposed:
        return baseline
    by_refs = {s.stroke_refs: s.content for s in proposed.spans}
    if {s.stroke_refs for s in baseline.spans} != set(by_refs):
        raise ValueError('The cover changed source stroke associations.')
    spans = tuple(replace(s, content=by_refs[s.stroke_refs]) for s in baseline.spans)
    from collections import defaultdict, deque
    matches = defaultdict(deque)
    for e in baseline.elements:
        matches[(e.kind, e.name, e.raw)].append(e.source)
    elements = []
    for e in proposed.elements:
        sources = matches[(e.kind, e.name, e.raw)]
        elements.append(replace(e, source=sources.popleft() if sources else None))
    return replace(proposed, spans=spans, elements=tuple(elements))
