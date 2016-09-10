import io
import struct

try:
    import unittest2 as unittest
except ImportError:
    import unittest

import zstd


class TestDecompressor_decompress(unittest.TestCase):
    def test_empty_input(self):
        dctx = zstd.ZstdDecompressor()

        with self.assertRaisesRegexp(zstd.ZstdError, 'input data invalid'):
            dctx.decompress(b'')

    def test_invalid_input(self):
        dctx = zstd.ZstdDecompressor()

        with self.assertRaisesRegexp(zstd.ZstdError, 'input data invalid'):
            dctx.decompress(b'foobar')

    def test_no_content_size_in_frame(self):
        cctx = zstd.ZstdCompressor(write_content_size=False)
        compressed = cctx.compress(b'foobar')

        dctx = zstd.ZstdDecompressor()
        with self.assertRaisesRegexp(zstd.ZstdError, 'input data invalid'):
            dctx.decompress(compressed)

    def test_content_size_present(self):
        cctx = zstd.ZstdCompressor(write_content_size=True)
        compressed = cctx.compress(b'foobar')

        dctx = zstd.ZstdDecompressor()
        decompressed  = dctx.decompress(compressed)
        self.assertEqual(decompressed, b'foobar')

    def test_max_output_size(self):
        cctx = zstd.ZstdCompressor(write_content_size=False)
        source = b'foobar' * 256
        compressed = cctx.compress(source)

        dctx = zstd.ZstdDecompressor()
        # Will fit into buffer exactly the size of input.
        decompressed = dctx.decompress(compressed, max_output_size=len(source))
        self.assertEqual(decompressed, source)

        # Input size - 1 fails
        with self.assertRaisesRegexp(zstd.ZstdError, 'Destination buffer is too small'):
            dctx.decompress(compressed, max_output_size=len(source) - 1)

        # Input size + 1 works
        decompressed = dctx.decompress(compressed, max_output_size=len(source) + 1)
        self.assertEqual(decompressed, source)

        # A much larger buffer works.
        decompressed = dctx.decompress(compressed, max_output_size=len(source) * 64)
        self.assertEqual(decompressed, source)

    def test_stupidly_large_output_buffer(self):
        cctx = zstd.ZstdCompressor(write_content_size=False)
        compressed = cctx.compress(b'foobar' * 256)
        dctx = zstd.ZstdDecompressor()

        with self.assertRaises(MemoryError):
            dctx.decompress(compressed, max_output_size=2**62)

    def test_dictionary(self):
        samples = []
        for i in range(128):
            samples.append(b'foo' * 64)
            samples.append(b'bar' * 64)
            samples.append(b'foobar' * 64)

        d = zstd.train_dictionary(8192, samples)

        orig = b'foobar' * 16384
        cctx = zstd.ZstdCompressor(level=1, dict_data=d, write_content_size=True)
        compressed = cctx.compress(orig)

        dctx = zstd.ZstdDecompressor(dict_data=d)
        decompressed = dctx.decompress(compressed)

        self.assertEqual(decompressed, orig)

    def test_dictionary_multiple(self):
        samples = []
        for i in range(128):
            samples.append(b'foo' * 64)
            samples.append(b'bar' * 64)
            samples.append(b'foobar' * 64)

        d = zstd.train_dictionary(8192, samples)

        sources = (b'foobar' * 8192, b'foo' * 8192, b'bar' * 8192)
        compressed = []
        cctx = zstd.ZstdCompressor(level=1, dict_data=d, write_content_size=True)
        for source in sources:
            compressed.append(cctx.compress(source))

        dctx = zstd.ZstdDecompressor(dict_data=d)
        for i in range(len(sources)):
            decompressed = dctx.decompress(compressed[i])
            self.assertEqual(decompressed, sources[i])


class TestDecompressor_copy_stream(unittest.TestCase):
    def test_no_read(self):
        source = object()
        dest = io.BytesIO()

        dctx = zstd.ZstdDecompressor()
        with self.assertRaises(ValueError):
            dctx.copy_stream(source, dest)

    def test_no_write(self):
        source = io.BytesIO()
        dest = object()

        dctx = zstd.ZstdDecompressor()
        with self.assertRaises(ValueError):
            dctx.copy_stream(source, dest)

    def test_empty(self):
        source = io.BytesIO()
        dest = io.BytesIO()

        dctx = zstd.ZstdDecompressor()
        # TODO should this raise an error?
        r, w = dctx.copy_stream(source, dest)

        self.assertEqual(r, 0)
        self.assertEqual(w, 0)
        self.assertEqual(dest.getvalue(), b'')

    def test_large_data(self):
        source = io.BytesIO()
        for i in range(255):
            source.write(struct.Struct('>B').pack(i) * 16384)
        source.seek(0)

        compressed = io.BytesIO()
        cctx = zstd.ZstdCompressor()
        cctx.copy_stream(source, compressed)

        compressed.seek(0)
        dest = io.BytesIO()
        dctx = zstd.ZstdDecompressor()
        r, w = dctx.copy_stream(compressed, dest)

        self.assertEqual(r, len(compressed.getvalue()))
        self.assertEqual(w, len(source.getvalue()))


def decompress_via_writer(data):
    buffer = io.BytesIO()
    dctx = zstd.ZstdDecompressor()
    with dctx.write_to(buffer) as decompressor:
        decompressor.write(data)
    return buffer.getvalue()


class TestDecompressor_write_to(unittest.TestCase):
    def test_empty_roundtrip(self):
        cctx = zstd.ZstdCompressor()
        empty = cctx.compress(b'')
        self.assertEqual(decompress_via_writer(empty), b'')

    def test_large_roundtrip(self):
        chunks = []
        for i in range(255):
            chunks.append(struct.Struct('>B').pack(i) * 16384)
        orig = b''.join(chunks)
        cctx = zstd.ZstdCompressor()
        compressed = cctx.compress(orig)

        self.assertEqual(decompress_via_writer(compressed), orig)

    def test_multiple_calls(self):
        chunks = []
        for i in range(255):
            for j in range(255):
                chunks.append(struct.Struct('>B').pack(j) * i)

        orig = b''.join(chunks)
        cctx = zstd.ZstdCompressor()
        compressed = cctx.compress(orig)

        buffer = io.BytesIO()
        dctx = zstd.ZstdDecompressor()
        with dctx.write_to(buffer) as decompressor:
            pos = 0
            while pos < len(compressed):
                pos2 = pos + 8192
                decompressor.write(compressed[pos:pos2])
                pos += 8192
        self.assertEqual(buffer.getvalue(), orig)

    def test_dictionary(self):
        samples = []
        for i in range(128):
            samples.append(b'foo' * 64)
            samples.append(b'bar' * 64)
            samples.append(b'foobar' * 64)

        d = zstd.train_dictionary(8192, samples)

        orig = b'foobar' * 16384
        buffer = io.BytesIO()
        cctx = zstd.ZstdCompressor(dict_data=d)
        with cctx.write_to(buffer) as compressor:
            compressor.write(orig)

        compressed = buffer.getvalue()
        buffer = io.BytesIO()

        dctx = zstd.ZstdDecompressor(dict_data=d)
        with dctx.write_to(buffer) as decompressor:
            decompressor.write(compressed)

        self.assertEqual(buffer.getvalue(), orig)

    def test_memory_size(self):
        dctx = zstd.ZstdDecompressor()
        buffer = io.BytesIO()
        with dctx.write_to(buffer) as decompressor:
            size = decompressor.memory_size()

        self.assertGreater(size, 100000)