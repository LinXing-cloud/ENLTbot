web: gunicorn -b 0.0.0.0:$PORT -k gevent -w 1 main:app
worker: python bot_worker.py
