import asyncio
import unittest
from unittest.mock import patch
import httpx
import app as module

class BackendTests(unittest.TestCase):
    def request(self, **kwargs):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=module.app), base_url='http://test') as client:
                return await client.post('/api/transcribe', **kwargs)
        return asyncio.run(run())

    def test_auth_blocks_upload(self):
        with patch.object(module, 'ACCESS_TOKEN', 'private'):
            res = self.request(files={'file': ('sample.m4a', b'audio')})
        self.assertEqual(res.status_code, 401)

    def test_upload_limit(self):
        with patch.object(module, 'ACCESS_TOKEN', 'private'), patch.object(module, 'ELEVENLABS_API_KEY', 'test'), patch.object(module, 'MAX_UPLOAD_MB', 0):
            res = self.request(headers={'Authorization': 'Bearer private'}, files={'file': ('sample.m4a', b'audio')})
        self.assertEqual(res.status_code, 413)

    def test_real_multipart_serialization_and_response(self):
        captured = []
        def provider(req):
            captured.append(req.content)
            return httpx.Response(200, json={'text':'سلام.', 'words':[{'text':'سلام.', 'start':0, 'end':1, 'speaker_id':'speaker_0'}]})
        client_type = httpx.AsyncClient
        def factory(**kwargs):
            if 'transport' not in kwargs:
                kwargs['transport'] = httpx.MockTransport(provider)
            return client_type(**kwargs)
        with patch.object(module, 'ACCESS_TOKEN', 'private'), patch.object(module, 'ELEVENLABS_API_KEY', 'test'), patch.object(module.httpx, 'AsyncClient', factory):
            res = self.request(headers={'Authorization':'Bearer private'}, files={'file':('sample.m4a',b'audio')}, data={'language_code':'auto','keyterms':'IVC, pathology'})
        self.assertEqual(res.status_code,200, res.text)
        self.assertEqual(res.json()['segments'][0]['text'],'سلام.')
        self.assertIn(b'scribe_v2_medical',captured[0])
        self.assertEqual(captured[0].count(b'name="keyterms"'),2)
        self.assertNotIn(b'name="language_code"',captured[0])

    def test_pages_origin_preflight(self):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=module.app), base_url='http://test') as client:
                return await client.options('/api/transcribe',headers={'Origin':'https://rhadadi.github.io','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'authorization'})
        res=asyncio.run(run())
        self.assertEqual(res.status_code,200)
        self.assertEqual(res.headers['access-control-allow-origin'],'https://rhadadi.github.io')

if __name__ == '__main__': unittest.main()
