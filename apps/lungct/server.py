"""Explicitly enabled, loopback-only offline lung CT entry point."""
import argparse
import logging
from pathlib import Path
import secrets
from urllib.parse import urlsplit
from flask import Flask, jsonify, request, send_file, send_from_directory
from .core import owned
from .service import Service
from .viewer import coronal, image_png, locate


def create_app(service, *, enabled=False):
    if not enabled: raise ValueError('肺结节入口未启用；使用 --enable-lungct')
    app=Flask(__name__,static_folder='static'); token=secrets.token_urlsafe(32)
    app.config['MAX_CONTENT_LENGTH']=1024*1024

    @app.before_request
    def local_only():
        if request.host.split(':')[0] not in ('127.0.0.1','localhost'): return jsonify(error='只允许本机访问'),403
        if request.headers.get('Sec-Fetch-Site')=='cross-site': return jsonify(error='拒绝跨站请求'),403
        origin=request.headers.get('Origin')
        if origin and urlsplit(origin).netloc!=request.host: return jsonify(error='拒绝跨站请求'),403
        if request.method=='POST' and (not request.is_json or not secrets.compare_digest(request.headers.get('X-LungCT-Token',''),token)):
            return jsonify(error='请求校验失败，请刷新页面'),403

    @app.after_request
    def protection(response):
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' blob:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; connect-src 'self'"
        return response

    @app.errorhandler(ValueError)
    def bad_request(error): return jsonify(error=str(error)),400

    @app.errorhandler(KeyError)
    @app.errorhandler(TypeError)
    def invalid_request(error): return jsonify(error='请求字段缺失或类型不正确'),400

    @app.errorhandler(Exception)
    def private_error(error):
        from werkzeug.exceptions import HTTPException
        if isinstance(error,HTTPException):return jsonify(error='请求无法处理'),error.code
        return jsonify(error='本地操作失败，请检查存储权限或输入完整性'),500

    @app.get('/')
    def index(): return send_from_directory(app.static_folder,'index.html')

    @app.get('/api/session')
    def session(): return jsonify(token=token,notice='仅供科研，不用于临床诊断')

    @app.get('/api/state')
    def state(): return jsonify(service.state(request.args.get('project')))

    @app.post('/api/action')
    def action():
        payload=request.get_json();name=payload.pop('action')
        actions={'createProject':service.create_project,'importStudy':service.import_study,'selectSeries':service.select_series,
                 'startDraft':service.start_draft,'getDraft':service.get_draft,'addFinding':service.add_finding,
                 'reviseFinding':service.revise_finding,'undoFinding':service.undo_finding,
                 'completeCase':service.complete_case,'reopenCase':service.reopen_case,'findingHistory':service.finding_history,
                 'startRun':service.start_run,'getRun':service.get_run,
                 'exportPreview':service.export_preview,'exportSnapshots':service.export_snapshots,'lookupFinding':service.lookup_finding}
        if name not in actions: raise ValueError('未知操作')
        return jsonify(actions[name](**payload))

    @app.get('/api/image')
    def image():
        project=request.args['project'];series=request.args['series']
        volume,g=service.volume(project,series)
        center=float(request.args.get('center',-600));width=float(request.args.get('width',1500))
        if request.args.get('plane')=='coronal':
            array,_=coronal(volume,g,float(request.args['y']) if 'y' in request.args else None)
        else:
            index=int(request.args.get('index',0))
            if not 0<=index<len(volume):raise ValueError('切片索引超出范围')
            array=volume[index]
        return send_file(image_png(array,center,width),mimetype='image/png')

    @app.get('/api/locator')
    def locator():
        volume,g=service.volume(request.args['project'],request.args['series'])
        _,meta=coronal(volume,g,float(request.args['y']) if 'y' in request.args else None)
        return jsonify(meta)

    @app.post('/api/locate')
    def location():
        payload=request.get_json()
        series=owned(service.repo.read(),'series',payload['series'],payload['project'])
        return jsonify(locate(series,payload['point']))

    return app


def main():
    parser=argparse.ArgumentParser(description='肺结节 CT 科研工作站')
    parser.add_argument('--enable-lungct',action='store_true')
    parser.add_argument('--data-dir',type=Path,default=Path('data/lungct'))
    parser.add_argument('--allow-root',action='append',default=[])
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--model-bundle',type=Path)
    args=parser.parse_args()
    # No request logging: URLs and imported local paths never reach a log sink.
    logging.getLogger('werkzeug').disabled=True
    from .model import MonaiAdapter
    service=Service(args.data_dir,allowed_roots=args.allow_root,model=MonaiAdapter(args.model_bundle) if args.model_bundle else None)
    create_app(service,enabled=args.enable_lungct).run(host='127.0.0.1',port=args.port,debug=False,use_reloader=False)


if __name__=='__main__':main()
