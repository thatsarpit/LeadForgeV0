module.exports = {
    apps: [
        {
            name: "leadforge-api",
            script: "./venv/bin/uvicorn",
            args: "api.app:app --host 0.0.0.0 --port 8001",
            interpreter: "none",
            cwd: ".",
            watch: false,
            env: {
                NODE_ENV: "production",
                PYTHONPATH: "."
            }
        },
        {
            name: "leadforge-manager",
            script: "core/engine/slot_manager.py",
            interpreter: "python3",
            cwd: ".",
            watch: false,
            env: {
                PYTHONPATH: "."
            }
        },
        {
            name: "leadforge-frontend",
            script: "npm",
            args: "run preview -- --port 5173 --host",
            cwd: "./dashboards/client",
            watch: false,
            env: {
                NODE_ENV: "production"
            }
        }
    ]
};
