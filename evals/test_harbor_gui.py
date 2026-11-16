"""无网络的真实示范模块边界回归；浏览器运行证据另存。"""
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'skills/dyz-software/resources/harbor-demo/v1.2'


class HarborGuiTests(unittest.TestCase):
    def execute(self, code):
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=FIXTURE,
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_core_strict_duplicates_bool_unicode_and_csv(self):
        self.execute('''from core import convert,InputError,VERSION
import json
assert VERSION=='1.2'
raw=json.dumps([dict(id='A',label='a,b',value=0)]).encode()
assert convert(raw,True)==('id,label,value\\nA,"a,b",0\\n',1)
for rows,strict,error in [([dict(id='A',label='a',value=True)],False,'invalid_value'),
 ([dict(id='A',label='a',value=0)]*2,False,'duplicate_id'),
 ([dict(id='A',label='a',value=0,extra=1)],True,'unknown_field')]:
 try:convert(json.dumps(rows).encode(),strict)
 except InputError as e:assert str(e)==error
 else:raise AssertionError(error)
''')

    def test_loopback_host_and_origin_boundary(self):
        self.execute('''import io
from gui import application
for host,origin,expected in [('127.0.0.1:1234',None,'200'),('example.invalid',None,'403'),('127.0.0.1:1234','http://example.invalid','403'),('127.0.0.1:1234','http://127.0.0.1:1234','200')]:
 e=dict(HTTP_HOST=host,SERVER_PORT='1234',PATH_INFO='/convert',REQUEST_METHOD='POST',CONTENT_TYPE='application/json',CONTENT_LENGTH='2')
 e['wsgi.input']=io.BytesIO(b'[]')
 if origin:e['HTTP_ORIGIN']=origin
 statuses=[];list(application(e,lambda s,h:statuses.append(s)));assert statuses[0].startswith(expected)
''')

    def test_version_page_routes_body_limit_and_length(self):
        self.execute('''import io,json
from gui import application
for path,method,length,body,expected in [('/version','GET','0',b'','200'),('/','GET','0',b'','200'),('/convert','POST','65537',b'','413'),('/convert','POST','3',b'[]','400'),('/convert','GET','0',b'','405'),('/missing','GET','0',b'','404')]:
 e=dict(HTTP_HOST='127.0.0.1:1234',SERVER_PORT='1234',PATH_INFO=path,REQUEST_METHOD=method,CONTENT_TYPE='application/json',CONTENT_LENGTH=length)
 e['wsgi.input']=io.BytesIO(body);statuses=[];result=b''.join(application(e,lambda s,h:statuses.append(s)))
 assert statuses[0].startswith(expected)
 if path=='/version':assert json.loads(result)['version']=='1.2'
''')

    def test_cli_does_not_overwrite_existing_output(self):
        self.execute('''from pathlib import Path
import tempfile
from cli import main
with tempfile.TemporaryDirectory() as directory:
 p=Path(directory);(p/'in.json').write_bytes(b'[]');(p/'out.csv').write_bytes(b'keep')
 assert main([str(p/'in.json'),str(p/'out.csv')])==3
 assert (p/'out.csv').read_bytes()==b'keep'
''')


if __name__ == '__main__':
    unittest.main()
