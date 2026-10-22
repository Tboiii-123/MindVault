.PHONY: up down logs migrate makemigrations test lint fmt shell superuser

up:            ## start the full stack (api, worker, beat, postgres, redis, minio)
	docker compose up --build -d
down:
	docker compose down
logs:
	docker compose logs -f web worker
migrate:
	docker compose exec web python manage.py migrate
makemigrations:
	docker compose exec web python manage.py makemigrations
test:          ## run the test suite inside the container
	docker compose run --rm -e DJANGO_SETTINGS_MODULE=config.settings.test web pytest --cov=apps
lint:
	ruff check . && ruff format --check .
fmt:
	ruff check --fix . && ruff format .
shell:
	docker compose exec web python manage.py shell
superuser:
	docker compose exec web python manage.py createsuperuser
