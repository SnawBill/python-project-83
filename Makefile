install:
	uv sync

dev:
	uv run flask --debug --app page_analyzer:app run

PORT ?= 8000

start:
	uv run gunicorn -w 5 -b 0.0.0.0:$(PORT) page_analyzer:app

build:
	./build.sh

render-start:
	uv run gunicorn -w 5 -b 0.0.0.0:$(PORT) page_analyzer:app
