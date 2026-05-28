.PHONY: test test-cov docker-test-arch docker-test-debian docker-test-fedora clean

test:
	python -m pytest tests/ -v

test-cov:
	python -m pytest tests/ -v --cov=jarvis --cov-report=term-missing --cov-report=html

docker-test-arch:
	docker build -t jarvis-test:arch -f docker/Dockerfile.arch .
	docker run --rm jarvis-test:arch

docker-test-debian:
	docker build -t jarvis-test:debian -f docker/Dockerfile.debian .
	docker run --rm jarvis-test:debian

docker-test-fedora:
	docker build -t jarvis-test:fedora -f docker/Dockerfile.fedora .
	docker run --rm jarvis-test:fedora

clean:
	rm -rf .pytest_cache/ __pycache__/
	rm -rf htmlcov/ .coverage
	rm -rf *.egg-info/ dist/ build/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
