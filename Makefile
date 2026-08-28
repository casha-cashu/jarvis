.PHONY: test test-cov test-integration docker-test-arch docker-test-debian docker-test-fedora \
        docker-integration-i3 docker-integration-sway clean

# Интеграционные тесты требуют реального DE/аудио — без маркеров они
# вешают прогон (открывают микрофон/дисплей). Юниты: `make test`.
test:
	PYTHONPATH=. python3 -m pytest tests/ -v -m "not slow and not integration"

test-cov:
	PYTHONPATH=. python3 -m pytest tests/ -v -m "not slow and not integration" --cov=jarvis --cov-report=term-missing --cov-report=html

# Осмысленно только в Docker/i3-Sway-окружении (см. docker-integration-*)
test-integration:
	PYTHONPATH=. python3 -m pytest tests/integration/ -v

docker-test-arch:
	docker build -t jarvis-test:arch -f docker/Dockerfile.arch .
	docker run --rm jarvis-test:arch

docker-test-debian:
	docker build -t jarvis-test:debian -f docker/Dockerfile.debian .
	docker run --rm jarvis-test:debian

docker-test-fedora:
	docker build -t jarvis-test:fedora -f docker/Dockerfile.fedora .
	docker run --rm jarvis-test:fedora

docker-integration-i3:
	docker build --target integration -t jarvis-integration:i3 -f docker/Dockerfile.i3 .
	docker run --rm --cap-add=SYS_PTRACE --security-opt seccomp=unconfined jarvis-integration:i3

docker-integration-sway:
	docker build --target integration -t jarvis-integration:sway -f docker/Dockerfile.sway .
	docker run --rm --privileged jarvis-integration:sway

clean:
	rm -rf .pytest_cache/ __pycache__/
	rm -rf htmlcov/ .coverage
	rm -rf *.egg-info/ build/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
