from core.workers.indiamart_worker import IndiaMartWorker

WORKER_REGISTRY = {
    "indiamart": IndiaMartWorker,
}

def get_worker(worker_type: str):
    worker_type = worker_type.lower()
    if worker_type not in WORKER_REGISTRY:
        raise ValueError(f"Unknown worker type: {worker_type}")
    return WORKER_REGISTRY[worker_type]
