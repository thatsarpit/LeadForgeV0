module.exports = {
    apps: [
        {
            name: "leadforge-api",
            script: "api/app.py",
            interpreter: "python3",
            args: "",
            cwd: ".",
            watch: false,
            env: {
                PORT: 8001,
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
            args: "run preview -- --port 5173",
            cwd: "./dashboards/client",
            watch: false,
            env: {
                NODE_ENV: "production"
            }
        }
    ]
};
