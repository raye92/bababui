from app.src.formatter import Formatter


def test_batch_strip_unwraps_transcripts_without_overwriting_sources(tmp_path):
    source = tmp_path / 'input'
    source.mkdir()
    transcript = source / 'sample.txt'
    wrapped = (
        '          1         Q    Please describe the records you reviewed\n\n'
        '          2    before the examination.\n\n'
        '          3         A    Yes.\n\n'
        '                                                                       1'
    )
    transcript.write_text(wrapped, encoding='utf-8')
    destination = tmp_path / 'stripped'

    result = Formatter().batch_strip_formatting(source, destination)

    assert len(result['processed']) == 1 and not result['failed']
    assert (destination / 'sample.txt').read_text(encoding='utf-8') == (
        '     Q    Please describe the records you reviewed before the examination.\n'
        '     A    Yes.')
    assert transcript.read_text(encoding='utf-8') == wrapped
