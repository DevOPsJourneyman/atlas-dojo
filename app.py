from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import date, timedelta
import json
import math

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////data/dojo.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ─── Models ──────────────────────────────────────────────────────────────────

class Card(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    topic = db.Column(db.String(50), nullable=False)       # Docker, GitHub
    difficulty = db.Column(db.String(20), nullable=False)  # fundamental, intermediate, advanced
    card_type = db.Column(db.String(20), nullable=False)   # theory, practice, why, scenario
    front = db.Column(db.Text, nullable=False)             # question
    back = db.Column(db.Text, nullable=False)              # answer
    why = db.Column(db.Text, default='')                   # the reasoning behind it
    command = db.Column(db.Text, default='')               # for lab scenarios

class Progress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    card_id = db.Column(db.Integer, db.ForeignKey('card.id'), nullable=False, unique=True)
    times_seen = db.Column(db.Integer, default=0)
    times_easy = db.Column(db.Integer, default=0)
    times_good = db.Column(db.Integer, default=0)
    times_hard = db.Column(db.Integer, default=0)
    times_again = db.Column(db.Integer, default=0)
    streak = db.Column(db.Integer, default=0)
    last_rating = db.Column(db.String(10), default='')
    interval_days = db.Column(db.Integer, default=0)
    ease_factor = db.Column(db.Float, default=2.5)
    next_review = db.Column(db.Date, default=date.today)
    card = db.relationship('Card', backref='progress')


# ─── Spaced Repetition (SM-2 simplified) ─────────────────────────────────────

def calculate_next_review(progress, rating):
    """
    SM-2 algorithm — same one Anki uses.
    Rating: 'again', 'hard', 'good', 'easy'
    """
    ef = progress.ease_factor

    if rating == 'again':
        progress.interval_days = 1
        ef = max(1.3, ef - 0.2)
        progress.streak = 0
    elif rating == 'hard':
        progress.interval_days = max(1, math.ceil(progress.interval_days * 1.2))
        ef = max(1.3, ef - 0.15)
        progress.streak = max(0, progress.streak - 1)
    elif rating == 'good':
        if progress.interval_days == 0:
            progress.interval_days = 3
        else:
            progress.interval_days = math.ceil(progress.interval_days * ef)
        progress.streak += 1
    elif rating == 'easy':
        if progress.interval_days == 0:
            progress.interval_days = 7
        else:
            progress.interval_days = math.ceil(progress.interval_days * ef * 1.3)
        ef = ef + 0.1
        progress.streak += 1

    progress.ease_factor = round(min(max(ef, 1.3), 4.0), 2)
    progress.next_review = date.today() + timedelta(days=progress.interval_days)
    progress.last_rating = rating
    progress.times_seen += 1

    if rating == 'easy': progress.times_easy += 1
    elif rating == 'good': progress.times_good += 1
    elif rating == 'hard': progress.times_hard += 1
    elif rating == 'again': progress.times_again += 1

    return progress


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    today = date.today()

    due_count = db.session.query(Progress).filter(Progress.next_review <= today).count()
    total_cards = Card.query.count()
    seen_cards = db.session.query(Progress).filter(Progress.times_seen > 0).count()
    mastered = db.session.query(Progress).filter(Progress.streak >= 3).count()

    # Topic breakdown
    topics = db.session.query(Card.topic, db.func.count(Card.id)).group_by(Card.topic).all()

    # Difficulty breakdown
    difficulties = db.session.query(
        Card.difficulty, db.func.count(Card.id)
    ).group_by(Card.difficulty).all()

    return render_template('index.html',
        due_count=due_count,
        total_cards=total_cards,
        seen_cards=seen_cards,
        mastered=mastered,
        topics=topics,
        difficulties=difficulties,
        today=today
    )


@app.route('/review')
def review():
    today = date.today()
    topic = request.args.get('topic', '')
    difficulty = request.args.get('difficulty', '')

    query = db.session.query(Card).join(
        Progress, Card.id == Progress.card_id, isouter=True
    ).filter(
        db.or_(Progress.next_review <= today, Progress.id == None)
    )

    if topic:
        query = query.filter(Card.topic == topic)
    if difficulty:
        query = query.filter(Card.difficulty == difficulty)

    # Order: fundamentals first, then by due date
    difficulty_order = db.case(
        {'fundamental': 1, 'intermediate': 2, 'advanced': 3},
        value=Card.difficulty
    )
    cards = query.order_by(difficulty_order, Progress.next_review).all()

    topics = db.session.query(Card.topic).distinct().all()
    difficulties_list = ['fundamental', 'intermediate', 'advanced']

    return render_template('review.html',
        cards=cards,
        card_count=len(cards),
        topic=topic,
        difficulty=difficulty,
        topics=[t[0] for t in topics],
        difficulties=difficulties_list
    )


@app.route('/rate', methods=['POST'])
def rate():
    card_id = int(request.form['card_id'])
    rating = request.form['rating']
    return_to = request.form.get('return_to', 'review')

    progress = Progress.query.filter_by(card_id=card_id).first()
    if not progress:
        progress = Progress(card_id=card_id)
        db.session.add(progress)

    progress = calculate_next_review(progress, rating)
    db.session.commit()

    if return_to == 'lab':
        return redirect(url_for('lab'))
    return redirect(url_for('review'))


@app.route('/lab')
def lab():
    topic = request.args.get('topic', '')

    query = Card.query.filter_by(card_type='scenario')
    if topic:
        query = query.filter_by(topic=topic)

    scenarios = query.order_by(
        db.case({'fundamental': 1, 'intermediate': 2, 'advanced': 3}, value=Card.difficulty)
    ).all()

    # Get progress for each
    progress_map = {}
    for s in scenarios:
        p = Progress.query.filter_by(card_id=s.id).first()
        progress_map[s.id] = p

    topics = db.session.query(Card.topic).distinct().all()

    return render_template('lab.html',
        scenarios=scenarios,
        progress_map=progress_map,
        topic=topic,
        topics=[t[0] for t in topics]
    )


@app.route('/browse')
def browse():
    topic = request.args.get('topic', '')
    difficulty = request.args.get('difficulty', '')
    card_type = request.args.get('card_type', '')

    query = Card.query
    if topic:
        query = query.filter_by(topic=topic)
    if difficulty:
        query = query.filter_by(difficulty=difficulty)
    if card_type:
        query = query.filter_by(card_type=card_type)

    difficulty_order = db.case(
        {'fundamental': 1, 'intermediate': 2, 'advanced': 3},
        value=Card.difficulty
    )
    cards = query.order_by(Card.topic, difficulty_order).all()

    progress_map = {}
    for c in cards:
        p = Progress.query.filter_by(card_id=c.id).first()
        progress_map[c.id] = p

    topics = db.session.query(Card.topic).distinct().all()
    difficulties = ['fundamental', 'intermediate', 'advanced']
    types = ['theory', 'practice', 'why', 'scenario']

    return render_template('browse.html',
        cards=cards,
        progress_map=progress_map,
        topic=topic,
        difficulty=difficulty,
        card_type=card_type,
        topics=[t[0] for t in topics],
        difficulties=difficulties,
        types=types
    )


# ─── Seed Data ───────────────────────────────────────────────────────────────

def seed_topic(topic, cards):
    """Add cards for a topic only if that topic has no cards yet."""
    if Card.query.filter_by(topic=topic).count() > 0:
        return
    for card in cards:
        db.session.add(card)
    db.session.flush()
    for card in Card.query.filter_by(topic=topic).all():
        if not Progress.query.filter_by(card_id=card.id).first():
            db.session.add(Progress(card_id=card.id, next_review=date.today()))
    db.session.commit()


def seed_database():
    docker_github_cards = [

        # ── DOCKER — FUNDAMENTAL ─────────────────────────────────────────────

        Card(topic='Docker', difficulty='fundamental', card_type='theory',
            front='What is a container and how does it differ from a VM?',
            back='A container is an isolated process that shares the host OS kernel. A VM virtualises hardware and runs its own full OS kernel. Containers are lighter, start faster, and use less memory — but share the host kernel rather than being fully isolated.',
            why='This is always the first Docker interview question. Interviewers want to know you understand the fundamental architecture difference, not just that containers "are like VMs but lighter."'),

        Card(topic='Docker', difficulty='fundamental', card_type='theory',
            front='What is the difference between a Docker image and a container?',
            back='An image is a read-only blueprint — a layered filesystem snapshot. A container is a running instance of that image with a writable layer on top. One image can run many containers simultaneously.',
            why='Images are immutable. Containers are ephemeral. Understanding this distinction explains why you use volumes for persistent data.'),

        Card(topic='Docker', difficulty='fundamental', card_type='theory',
            front='What is a Dockerfile?',
            back='A Dockerfile is a text file containing instructions that Docker executes sequentially to build an image. Each instruction creates a new read-only layer. The final image is the sum of all layers.',
            why='Every instruction is a layer. Order matters for caching. This is the foundation of understanding build performance.'),

        Card(topic='Docker', difficulty='fundamental', card_type='practice',
            front='What command builds an image from a Dockerfile in the current directory and tags it?',
            back='docker build -t my-app:latest .\n\n-t sets the name:tag\n. tells Docker where to find the Dockerfile (current directory)',
            why='The . is the build context — Docker sends everything in that directory to the daemon. .dockerignore controls what gets included.',
            command='docker build -t my-app:latest .'),

        Card(topic='Docker', difficulty='fundamental', card_type='practice',
            front='How do you run a container in detached mode with port mapping?',
            back='docker run -d -p 8080:80 --name my-container nginx\n\n-d = detached (background)\n-p host:container = port mapping\n--name = assign a name',
            why='Detached mode is how you run production containers. Without -d your terminal is locked to the container output.',
            command='docker run -d -p 8080:80 --name my-container nginx'),

        Card(topic='Docker', difficulty='fundamental', card_type='practice',
            front='How do you see all running containers? What about stopped ones too?',
            back='docker ps              # running only\ndocker ps -a           # all including stopped\n\nStopped containers still exist until you remove them with docker rm.',
            why='Stopped containers consume disk space. This is why docker system prune exists — to clean up stopped containers, dangling images, and unused volumes.',
            command='docker ps\ndocker ps -a'),

        Card(topic='Docker', difficulty='fundamental', card_type='practice',
            front='How do you view the logs of a running container?',
            back='docker logs my-container           # all logs\ndocker logs my-container --follow  # live stream\ndocker logs my-container --tail 50 # last 50 lines',
            why='This is your first diagnostic tool when something breaks. In production, logs get shipped to centralised logging (ELK, Grafana Loki). In your home lab, docker logs is your window into the container.',
            command='docker logs my-container --follow'),

        Card(topic='Docker', difficulty='fundamental', card_type='practice',
            front='How do you run a command inside a running container?',
            back='docker exec -it my-container bash\n\n-i = interactive (keep stdin open)\n-t = allocate a pseudo-TTY (terminal)\nbash = the command to run\n\nUse sh if bash is not available (alpine images).',
            why='exec runs a new process inside an existing container without stopping it. Essential for debugging — you can inspect files, check environment variables, run queries.',
            command='docker exec -it my-container bash'),

        Card(topic='Docker', difficulty='fundamental', card_type='why',
            front='Why do we COPY requirements.txt before COPY . . in a Dockerfile?',
            back='Layer caching. Docker caches each layer. If requirements.txt has not changed, Docker reuses the cached pip install layer and skips it entirely. If you copy everything first, any code change invalidates the cache and forces a full pip install every build.',
            why='This is a fundamental optimisation. On a large project the difference can be 30 seconds vs 3 minutes per build. Interviewers ask this to see if you understand how layers work in practice.'),

        Card(topic='Docker', difficulty='fundamental', card_type='why',
            front='Why use python:3.12-slim instead of python:3.12?',
            back='The slim variant removes documentation, man pages, and build tools not needed at runtime. Result: ~150MB image vs ~900MB. Smaller images mean faster pulls, less storage, smaller attack surface.',
            why='Image size is a real operational concern. In a CI/CD pipeline you pull images on every build. A 900MB image on 100 builds/day is expensive and slow.'),

        Card(topic='Docker', difficulty='fundamental', card_type='theory',
            front='What does EXPOSE do in a Dockerfile?',
            back='EXPOSE documents which port the application listens on. It does NOT publish the port or make it accessible from the host. Publishing happens at runtime with -p or in docker-compose.yml.',
            why='EXPOSE is documentation. It tells other developers and tools "this container listens on this port." The actual port binding is a runtime decision, not a build-time decision.'),

        Card(topic='Docker', difficulty='fundamental', card_type='scenario',
            front='Your container starts and immediately exits. How do you diagnose it?',
            back='1. docker ps -a              # confirm it exited\n2. docker logs <container>   # read the error output\n3. docker inspect <container> # check exit code and config\n\nCommon causes: app crash on startup, missing env var, wrong CMD, missing file.',
            why='Containers exit when their main process exits. If your app crashes immediately, the container stops. Logs tell you why.',
            command='docker ps -a\ndocker logs <container>\ndocker inspect <container>'),

        Card(topic='Docker', difficulty='fundamental', card_type='scenario',
            front='You need to get inside a running container to check a config file. What do you run?',
            back='docker exec -it <container-name> bash\n\nThen navigate like a normal Linux shell:\ncat /app/config.py\nls /data\nenv | grep DATABASE',
            why='exec is non-destructive — you are not restarting the container, just running an additional process inside it. Safe for production debugging.',
            command='docker exec -it <container-name> bash'),


        # ── DOCKER — INTERMEDIATE ─────────────────────────────────────────────

        Card(topic='Docker', difficulty='intermediate', card_type='theory',
            front='What is the difference between CMD and ENTRYPOINT?',
            back='ENTRYPOINT sets the main executable — it always runs and cannot be overridden without --entrypoint flag.\nCMD provides default arguments — easily overridden by passing arguments to docker run.\n\nCombined: ENTRYPOINT ["python"] CMD ["app.py"] — you can swap app.py without changing the entrypoint.',
            why='Understanding this distinction shows you know how containers are designed to be composable. ENTRYPOINT for the binary, CMD for the default arguments.'),

        Card(topic='Docker', difficulty='intermediate', card_type='theory',
            front='What is the difference between exec form and shell form in CMD?',
            back='Exec form: CMD ["python", "app.py"]  — process runs as PID 1, receives OS signals directly\nShell form: CMD python app.py — runs via /bin/sh -c, PID 1 is the shell, signals may not reach your app\n\nAlways use exec form for the main process.',
            why='Graceful shutdown depends on your app receiving SIGTERM. If the shell is PID 1 instead of your app, SIGTERM goes to the shell and your app gets killed hard. This causes data corruption in databases.'),

        Card(topic='Docker', difficulty='intermediate', card_type='theory',
            front='What is a named volume and how does it differ from a bind mount?',
            back='Named volume: docker managed, lives at /var/lib/docker/volumes/. Portable, survives docker compose down.\n\nBind mount: maps a specific host path into the container. Host-dependent, good for development (live code reloading).\n\nNamed volumes for production data. Bind mounts for development.',
            why='This is a common interview question. Named volumes are the right choice for databases and persistent data because they are managed by Docker and not tied to host filesystem paths.'),

        Card(topic='Docker', difficulty='intermediate', card_type='practice',
            front='What does docker inspect do and when would you use it?',
            back='docker inspect <container>\n\nReturns full JSON metadata: network config, mounts, env vars, restart policy, exit code, image layers.\n\nUse it when: debugging network issues, checking what volumes are mounted, verifying env vars were passed correctly.',
            why='inspect is the source of truth for what Docker thinks about your container. When something behaves unexpectedly, inspect tells you exactly what configuration Docker is using.',
            command='docker inspect <container>\ndocker inspect <container> | grep -i ip  # filter for specific fields'),

        Card(topic='Docker', difficulty='intermediate', card_type='practice',
            front='How do you check resource usage (CPU/memory) of running containers?',
            back='docker stats                    # live stream all containers\ndocker stats <container-name>   # specific container\ndocker stats --no-stream        # single snapshot, no live update',
            why='In production you use proper monitoring (Prometheus/Grafana — Week 7). But docker stats is your quick diagnostic tool. If a container is consuming all CPU it is usually an infinite loop or a stuck process.',
            command='docker stats\ndocker stats --no-stream'),

        Card(topic='Docker', difficulty='intermediate', card_type='why',
            front='Why use restart: unless-stopped in docker-compose.yml?',
            back='unless-stopped means: restart automatically on crash or host reboot, but NOT if you manually run docker compose down.\n\nOptions:\n- no: never restart (default)\n- always: always restart, even after manual stop\n- on-failure: only restart on non-zero exit code\n- unless-stopped: best for long-running services',
            why='always is dangerous — if you stop a container deliberately it will keep restarting. unless-stopped respects your intent. This is the right default for production services on a home lab.'),

        Card(topic='Docker', difficulty='intermediate', card_type='theory',
            front='What is the Docker build context and why does it matter?',
            back='The build context is the directory you pass to docker build (usually .). Docker sends all files in that directory to the daemon before building.\n\nIf your context is 2GB, Docker transfers 2GB before starting. .dockerignore excludes files from the context, making builds faster.',
            why='On a project with large datasets or node_modules, a missing .dockerignore can make builds take minutes longer than necessary. This is a real operational issue.'),

        Card(topic='Docker', difficulty='intermediate', card_type='scenario',
            front='You updated app.py and rebuilt the image. The pip install layer took 45 seconds again. What went wrong?',
            back='The COPY order in the Dockerfile is wrong. If COPY . . comes before the pip install, any code change invalidates the cache at that layer and forces a full reinstall.\n\nFix:\n1. COPY requirements.txt .\n2. RUN pip install -r requirements.txt\n3. COPY . .\n\nNow pip only reruns when requirements.txt changes.',
            why='Layer cache invalidation is sequential — once a layer is invalidated, all subsequent layers are rebuilt. Order your Dockerfile from least-changing to most-changing.',
            command='# Wrong order:\nCOPY . .\nRUN pip install -r requirements.txt\n\n# Correct order:\nCOPY requirements.txt .\nRUN pip install -r requirements.txt\nCOPY . .'),

        Card(topic='Docker', difficulty='intermediate', card_type='scenario',
            front='You ran docker compose down and your database data is gone. What happened and how do you prevent it?',
            back='docker compose down removes containers and networks but NOT named volumes — unless you used -v flag.\n\nIf data is gone, either:\n1. You used docker compose down -v (deletes volumes)\n2. You used a bind mount and deleted the host directory\n3. Data was stored inside the container filesystem (no volume at all)\n\nFix: always use a named volume for database data in docker-compose.yml.',
            why='This is a painful lesson people learn in production. Named volumes persist independently of containers. The container is disposable — the data is not.',
            command='# Safe teardown:\ndocker compose down          # preserves volumes\n\n# Nuclear option (data loss):\ndocker compose down -v       # deletes volumes too'),


        # ── DOCKER — ADVANCED ─────────────────────────────────────────────────

        Card(topic='Docker', difficulty='advanced', card_type='theory',
            front='What is a multi-stage build and why would you use it?',
            back='Multi-stage builds use multiple FROM instructions in one Dockerfile. Early stages compile or build the app. The final stage copies only the compiled output, leaving build tools behind.\n\nResult: production image contains only what is needed to run — not compilers, test frameworks, or source code.',
            why='A Go app compiled with all build tools might be 800MB. The same app in a multi-stage build running on scratch or alpine might be 10MB. Smaller = faster pulls, less attack surface, lower storage costs.'),

        Card(topic='Docker', difficulty='advanced', card_type='theory',
            front='What is the difference between COPY and ADD in a Dockerfile?',
            back='COPY: copies files from build context into the image. Simple and explicit.\nADD: does everything COPY does, plus:\n- Extracts tar archives automatically\n- Can fetch from URLs\n\nBest practice: always use COPY unless you specifically need ADD features. ADD behaviour can be surprising.',
            why='The Dockerfile best practices guide explicitly recommends COPY over ADD for clarity. Using ADD when you mean COPY is a red flag in code review.'),

        Card(topic='Docker', difficulty='advanced', card_type='theory',
            front='What is the difference between ENV and ARG in a Dockerfile?',
            back='ARG: build-time variable. Available only during docker build. Not present in the final image or running container.\n\nENV: runtime variable. Available during build AND in running containers.\n\nUse ARG for build configuration (version numbers). Use ENV for app configuration (database URLs). Never use ENV for secrets.',
            why='Secrets in ENV vars are visible via docker inspect. Use Docker secrets or external secret managers for sensitive values. ARG values are not persisted in the final image layers.'),

        Card(topic='Docker', difficulty='advanced', card_type='scenario',
            front='How would you add a health check to a Dockerfile so Docker knows when your Flask app is ready?',
            back='HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \\\n  CMD curl -f http://localhost:5000/ || exit 1\n\nDocker will mark the container as healthy/unhealthy based on the exit code. Visible in docker ps under STATUS.',
            why='Without a health check, Docker considers a container healthy the moment the process starts — even if your app takes 10 seconds to initialise. Health checks are essential for zero-downtime deployments.',
            command='HEALTHCHECK --interval=30s --timeout=10s --retries=3 \\\n  CMD curl -f http://localhost:5000/ || exit 1'),

        Card(topic='Docker', difficulty='advanced', card_type='theory',
            front='What are the three Docker network modes and when would you use each?',
            back='bridge (default): containers get their own network namespace, communicate via Docker network. Use for most apps.\n\nhost: container shares the host network stack. No isolation. Use when you need maximum network performance.\n\nnone: no networking. Container is completely isolated. Use for batch jobs that need no network access.',
            why='Docker Compose creates a bridge network by default. Services in the same Compose file can reach each other by service name (DNS). This is how Flask talks to Postgres without hardcoding IPs.'),


        # ── DOCKER COMPOSE ────────────────────────────────────────────────────

        Card(topic='Docker', difficulty='fundamental', card_type='theory',
            front='What is Docker Compose and what problem does it solve?',
            back='Docker Compose is a tool for defining and running multi-container applications using a YAML file (docker-compose.yml). Instead of running multiple docker run commands with many flags, you declare the entire stack once and manage it with simple commands.',
            why='In the real world, apps have multiple services — web app, database, cache, queue. Compose lets you define all of them, their relationships, volumes, and networks in one file. One command to start everything.'),

        Card(topic='Docker', difficulty='fundamental', card_type='practice',
            front='What are the essential docker compose commands?',
            back='docker compose up -d           # start all services detached\ndocker compose up -d --build   # rebuild images then start\ndocker compose down            # stop and remove containers\ndocker compose down -v         # also delete volumes (data loss!)\ndocker compose logs -f         # follow logs for all services\ndocker compose ps              # status of all services\ndocker compose restart         # restart all services',
            why='These are your daily commands. --build is essential when you have changed code. Without it, Compose uses the cached image even if your Dockerfile changed.',
            command='docker compose up -d --build\ndocker compose logs -f\ndocker compose ps'),

        Card(topic='Docker', difficulty='intermediate', card_type='why',
            front='Why does docker-compose.yml use depends_on and what are its limits?',
            back='depends_on controls startup order — ensures service B starts after service A.\n\nThe limit: depends_on only waits for the container to start, NOT for the service inside to be ready. A database container can be "started" but still initialising.\n\nFor true readiness, combine with health checks and condition: service_healthy.',
            why='This catches many people out. Your app container starts, tries to connect to the database, fails because Postgres is still initialising, and crashes. Health checks + depends_on condition solve this properly.'),


        # ── DOCKER HUB ────────────────────────────────────────────────────────

        Card(topic='Docker', difficulty='fundamental', card_type='practice',
            front='How do you push an image to Docker Hub?',
            back='# 1. Login\ndocker login -u yourusername\n\n# 2. Tag the image correctly\ndocker tag local-image:latest username/repo-name:latest\n\n# 3. Push\ndocker push username/repo-name:latest\n\nImage must be tagged as username/repo-name for Docker Hub to accept it.',
            why='The tag format tells Docker where to push. docker.io/username/repo is the full path. When you tag correctly, Docker knows which registry and repository to send it to.',
            command='docker login -u yourusername\ndocker tag my-app:latest username/my-app:latest\ndocker push username/my-app:latest'),

        Card(topic='Docker', difficulty='fundamental', card_type='why',
            front='Why use a Personal Access Token (PAT) instead of your password for docker login?',
            back='PATs can be:\n- Scoped to specific permissions (read-only, read-write)\n- Revoked individually without changing your password\n- Named per machine (zeus01, laptop, CI server)\n\nIf a server is compromised, you revoke that token — your account and other tokens are safe.',
            why='This is standard security practice. Credentials stored on servers should never be your main account password. This principle applies everywhere: GitHub PATs, AWS access keys, API tokens.'),

        Card(topic='Docker', difficulty='intermediate', card_type='theory',
            front='When you push an image, why do some layers say "Layer already exists"?',
            back='Docker images are made of shared layers. If a layer (e.g. python:3.12-slim base layers) already exists on Docker Hub from a previous push, Docker skips uploading it.\n\nOnly layers unique to your image get uploaded. This makes pushes fast and saves bandwidth.',
            why='This is the same layer caching system working in reverse. On pull, Docker only downloads layers it does not have locally. On push, it only uploads layers the registry does not have.'),


    ]

    github_cards = [

        # ── GITHUB — FUNDAMENTAL ─────────────────────────────────────────────

        Card(topic='GitHub', difficulty='fundamental', card_type='theory',
            front='What is the difference between Git and GitHub?',
            back='Git: a distributed version control system that runs locally on your machine. Tracks file changes, manages branches, records history.\n\nGitHub: a cloud hosting platform for Git repositories. Adds collaboration features — pull requests, Issues, Actions, permissions.',
            why='Git works without GitHub. GitHub is built on top of Git. Knowing this distinction shows you understand the tool, not just the platform.'),

        Card(topic='GitHub', difficulty='fundamental', card_type='practice',
            front='What is the git workflow for making and saving a change?',
            back='git status                    # see what changed\ngit add .                     # stage all changes\ngit add specific-file.py      # stage one file\ngit commit -m "feat: description"  # commit with message\ngit push                      # push to remote',
            why='git add is a deliberate staging step — you choose what goes into the commit. This lets you make multiple changes but commit them separately with meaningful messages.',
            command='git status\ngit add .\ngit commit -m "feat: add login page"\ngit push'),

        Card(topic='GitHub', difficulty='fundamental', card_type='why',
            front='Why use conventional commit messages like feat:, fix:, docs:?',
            back='Conventional commits create a readable history:\nfeat: new feature\nfix: bug fix\ndocs: documentation only\nrefactor: code change with no feature/fix\nchore: maintenance (deps, config)\n\nBenefits: auto-generate changelogs, semantic versioning, readable git log, professional signal to reviewers.',
            why='In a team, git log is how you understand what happened. "fixed stuff" tells you nothing. "fix: resolve SQLite connection timeout on container restart" tells you everything.'),

        Card(topic='GitHub', difficulty='fundamental', card_type='practice',
            front='How do you connect a local folder to a GitHub repository?',
            back='git init                                    # initialise local repo\ngit add .\ngit commit -m "feat: initial commit"\ngit branch -M main                          # rename branch to main\ngit remote add origin <github-url>          # link to GitHub\ngit push -u origin main                     # push and set upstream',
            why='-u sets the upstream tracking branch. After this, git push alone knows where to push without specifying origin main every time.',
            command='git init\ngit remote add origin https://github.com/user/repo.git\ngit push -u origin main'),

        Card(topic='GitHub', difficulty='fundamental', card_type='theory',
            front='What is .gitignore and why is it important?',
            back='.gitignore tells Git which files to never track. Common entries:\n__pycache__/, *.pyc (Python cache)\n.env (secrets and environment variables)\n*.db (local databases)\nnode_modules/ (dependencies)\n\nWithout it you accidentally commit secrets, binaries, or gigabytes of dependencies.',
            why='Committing a .env file with database passwords to a public GitHub repo is one of the most common security incidents. .gitignore prevents it. Add it before your first commit.'),

        Card(topic='GitHub', difficulty='fundamental', card_type='scenario',
            front='You accidentally committed a file with a password in it. What do you do?',
            back='1. Assume the secret is compromised — rotate it immediately\n2. Remove from the latest commit: git rm --cached .env\n3. Add to .gitignore\n4. Commit the removal\n5. To remove from history: git filter-branch or BFG Repo Cleaner\n\nNote: even after removal, the secret was in the public history. Always rotate first.',
            why='Secrets in git history are permanently compromised. GitHub scans for exposed secrets and notifies services automatically. The secret must be rotated — removing it from history alone is not enough.',
            command='git rm --cached .env\necho ".env" >> .gitignore\ngit add .gitignore\ngit commit -m "fix: remove accidentally committed env file"'),


        # ── GITHUB — INTERMEDIATE ─────────────────────────────────────────────

        Card(topic='GitHub', difficulty='intermediate', card_type='theory',
            front='What is a branch and why do you use them?',
            back='A branch is an independent line of development. main (or master) is the stable branch. Feature branches let you develop without affecting stable code.\n\ngit checkout -b feature/login   # create and switch\ngit push origin feature/login    # push to GitHub\n# when done: merge via pull request',
            why='Branching protects your main branch. In a team, no one pushes directly to main — everything goes through a branch and a pull request. This is the industry standard workflow.',
            command='git checkout -b feature/my-feature\ngit push origin feature/my-feature'),

        Card(topic='GitHub', difficulty='intermediate', card_type='theory',
            front='What is a Pull Request (PR)?',
            back='A PR is a request to merge code from one branch into another. It creates a review space where:\n- Code can be reviewed before merging\n- Automated tests run (GitHub Actions)\n- Comments and discussions happen\n- Changes are requested or approved\n\nPRs are the core collaboration mechanism in modern software teams.',
            why='Even working alone, PRs are good practice. They force you to review your own diff before merging. Your GitHub portfolio shows PRs — recruiters look at this.'),

        Card(topic='GitHub', difficulty='intermediate', card_type='practice',
            front='How do you undo the last commit without losing your changes?',
            back='git reset HEAD~1\n\nThis moves HEAD back one commit but keeps your changes staged. The commit is gone but your files are untouched.\n\ngit reset --hard HEAD~1  # also discards file changes (destructive)\ngit revert HEAD          # creates a new commit that undoes the previous one (safe for shared branches)',
            why='reset rewrites history — dangerous on shared branches. revert is safe because it adds a new commit rather than removing one. On your own branch, reset is fine.',
            command='git reset HEAD~1          # undo commit, keep changes\ngit reset --hard HEAD~1   # undo commit AND changes\ngit revert HEAD           # safe undo on shared branches'),

        Card(topic='GitHub', difficulty='intermediate', card_type='practice',
            front='How do you save work in progress without committing?',
            back='git stash           # stash current changes\ngit stash pop       # restore stashed changes\ngit stash list      # see all stashes\ngit stash drop      # delete a stash\n\nUseful when you need to switch branches urgently without committing half-finished work.',
            why='Stash is a temporary shelf. You are in the middle of a feature, an urgent fix comes in, you stash your work, fix the bug on main, come back and pop your stash.',
            command='git stash\ngit stash pop'),

        Card(topic='GitHub', difficulty='intermediate', card_type='theory',
            front='What is the difference between git merge and git rebase?',
            back='merge: combines branches by creating a merge commit. Preserves full history of both branches. History can look messy with many branches.\n\nrebase: replays your commits on top of another branch. Creates a linear history. Rewrites commit hashes — never rebase shared/public branches.',
            why='Teams have strong opinions on merge vs rebase. Know both. Linear history (rebase) is easier to read. Merge preserves exact branch history. Either way, understand that rebase rewrites history and is destructive on shared branches.'),

        Card(topic='GitHub', difficulty='intermediate', card_type='scenario',
            front='You cloned a repo and now the remote has new commits. How do you get them?',
            back='git fetch           # download remote changes without merging\ngit pull            # fetch + merge in one step\ngit pull --rebase   # fetch + rebase instead of merge\n\ngit fetch is safer — it lets you inspect changes before merging. git pull is convenient for solo work.',
            why='In a team, always fetch first and check what changed before pulling. In CI/CD pipelines, git fetch is preferred because it does not modify your working branch.',
            command='git fetch origin\ngit log origin/main  # inspect what changed\ngit merge origin/main'),

        Card(topic='GitHub', difficulty='intermediate', card_type='theory',
            front='What are GitHub Issues and how do DevOps engineers use them?',
            back='Issues are GitHub\'s built-in task tracker. DevOps engineers use them to:\n- Track bugs with reproduction steps\n- Document feature requests with acceptance criteria\n- Capture tech debt\n- Link to PRs that fix them (closes #42 in commit message)\n- Create a visible backlog for a project',
            why='A GitHub profile with active Issues shows you think like an engineer — you capture requirements, prioritise work, and track decisions. Recruiters can see your Issues. Make them meaningful.'),

        Card(topic='GitHub', difficulty='advanced', card_type='theory',
            front='What is GitHub Actions and how does it relate to CI/CD?',
            back='GitHub Actions is GitHub\'s built-in CI/CD platform. Workflows are defined in .github/workflows/*.yml files. Triggers include push, PR, schedule, or manual.\n\nA basic CI pipeline: push code → Actions runs tests → builds Docker image → pushes to registry.\n\nThis is Week 6 of your roadmap.',
            why='Every modern DevOps role uses some CI/CD platform. GitHub Actions is the most accessible because it is built into GitHub and free for public repos. Understanding the concept now makes Week 6 easier.'),
    ]

    seed_topic('Docker', docker_github_cards)
    seed_topic('GitHub', github_cards)

    # ── KUBERNETES ────────────────────────────────────────────────────────────

    kubernetes_cards = [

        # FUNDAMENTAL

        Card(topic='Kubernetes', difficulty='fundamental', card_type='theory',
            front='What is Kubernetes and what problem does it solve?',
            back='Kubernetes (k8s) is a container orchestration platform. It automates deployment, scaling, and management of containerised applications across a cluster of machines.\n\nProblem it solves: Docker alone runs containers on one host. Kubernetes runs them across many hosts, handles failures, scales up/down, and routes traffic — automatically.',
            why='This is always question one in a k8s interview. The key word is orchestration — Kubernetes does not replace Docker, it orchestrates containers across a fleet of machines.'),

        Card(topic='Kubernetes', difficulty='fundamental', card_type='theory',
            front='What is a Pod?',
            back='A Pod is the smallest deployable unit in Kubernetes. It wraps one or more containers that share:\n- The same network namespace (same IP)\n- The same storage volumes\n- The same lifecycle\n\nMost Pods run a single container. Multi-container Pods are used for sidecars (e.g., a log shipper alongside your app).',
            why='You never run containers directly in k8s — you run Pods. Understanding this is the foundation of everything else. Pods are ephemeral — when they die, they are replaced with new ones at new IPs.'),

        Card(topic='Kubernetes', difficulty='fundamental', card_type='theory',
            front='What is a Node?',
            back='A Node is a machine (VM or physical) in the Kubernetes cluster. There are two types:\n\nControl plane node: runs the Kubernetes API server, scheduler, and controller manager. Manages the cluster.\n\nWorker node: runs your application Pods. Has kubelet (node agent) and a container runtime (containerd).',
            why='In your home lab: zeus01 is the control plane, zeus02/03 are workers. This maps directly to production architectures — managed k8s (EKS, GKE) hides the control plane from you.'),

        Card(topic='Kubernetes', difficulty='fundamental', card_type='theory',
            front='What is a Deployment?',
            back='A Deployment manages a set of identical Pods. It ensures:\n- A specified number of replicas are always running\n- Rolling updates with zero downtime\n- Rollback to a previous version if an update fails\n\nYou rarely create Pods directly — you create Deployments which create and manage Pods for you.',
            why='The Deployment is the core workload object. It adds the self-healing and update management that raw Pods lack. If a Pod crashes, the Deployment controller replaces it automatically.'),

        Card(topic='Kubernetes', difficulty='fundamental', card_type='theory',
            front='What is a Service and why do you need it if you already have Pods?',
            back='A Service provides a stable network endpoint for a set of Pods. Pods are ephemeral — they get new IPs every time they restart. A Service has a fixed IP and DNS name that never changes.\n\nService uses label selectors to find its target Pods. Traffic hits the Service, which load-balances to healthy Pods.',
            why='Without a Service, you would need to track Pod IPs manually — impossible at scale. Service is the network abstraction that decouples consumers from the Pod lifecycle.'),

        Card(topic='Kubernetes', difficulty='fundamental', card_type='practice',
            front='What are the essential kubectl commands for seeing what is running?',
            back='kubectl get pods                    # all pods in current namespace\nkubectl get pods -A                # all pods in all namespaces\nkubectl get all                    # pods, services, deployments, replicasets\nkubectl get nodes                  # cluster nodes and their status\nkubectl get pods -o wide           # includes node and IP columns',
            why='These are your first commands when something is wrong. -A (all namespaces) is essential because your app might be in a different namespace from where you are looking.',
            command='kubectl get pods\nkubectl get all\nkubectl get nodes'),

        Card(topic='Kubernetes', difficulty='fundamental', card_type='practice',
            front='How do you apply a manifest file and check what happened?',
            back='kubectl apply -f deployment.yaml         # create or update resources\nkubectl apply -f ./manifests/            # apply all files in a directory\nkubectl get pods -w                      # watch pods update in real time\nkubectl rollout status deployment/myapp  # wait for rollout to complete',
            why='apply is idempotent — safe to run multiple times. It creates the resource if it does not exist, updates it if it does. This is the core of GitOps: your YAML is the source of truth.',
            command='kubectl apply -f deployment.yaml\nkubectl rollout status deployment/myapp'),

        Card(topic='Kubernetes', difficulty='fundamental', card_type='practice',
            front='How do you debug a Pod that is not starting?',
            back='kubectl get pods                          # check status (Pending, CrashLoopBackOff, etc.)\nkubectl describe pod <pod-name>          # full event log — shows scheduling errors, image pull failures\nkubectl logs <pod-name>                  # app stdout/stderr\nkubectl logs <pod-name> --previous       # logs from the crashed previous instance',
            why='describe shows Kubernetes-level events (could not pull image, insufficient resources, failed scheduling). logs shows your application output. You need both.',
            command='kubectl describe pod <pod-name>\nkubectl logs <pod-name>\nkubectl logs <pod-name> --previous'),

        Card(topic='Kubernetes', difficulty='fundamental', card_type='practice',
            front='How do you get a shell inside a running Pod?',
            back='kubectl exec -it <pod-name> -- bash\nkubectl exec -it <pod-name> -- sh    # if bash not available (alpine)\n\n# If the pod has multiple containers:\nkubectl exec -it <pod-name> -c <container-name> -- bash',
            why='Same concept as docker exec but for Pods. Essential for debugging — check env vars, test network connectivity, inspect files. The -- separates kubectl flags from the command.',
            command='kubectl exec -it <pod-name> -- bash'),

        Card(topic='Kubernetes', difficulty='fundamental', card_type='theory',
            front='What is a Namespace?',
            back='A Namespace is a virtual cluster within a Kubernetes cluster. It partitions resources into isolated groups.\n\nDefault namespaces:\n- default: where your resources go if you do not specify\n- kube-system: Kubernetes internal components (scheduler, DNS)\n- kube-public: publicly readable cluster info\n\nUse namespaces to separate environments (dev/staging/prod) or teams.',
            why='In your home lab, everything is in default. In production, teams and environments get separate namespaces for isolation, resource quotas, and RBAC permissions.'),

        Card(topic='Kubernetes', difficulty='fundamental', card_type='why',
            front='Why use YAML manifests instead of kubectl run?',
            back='kubectl run creates a Pod imperatively — the command is not saved anywhere and the config is not reproducible.\n\nYAML manifests are declarative — you describe the desired state. Benefits:\n- Version controlled in git\n- Repeatable across clusters\n- Reviewable via pull requests\n- Foundation of GitOps\n\nkubectl run is fine for quick debugging. Use manifests for everything real.',
            why='Declarative config is the entire philosophy of Kubernetes. The API server stores your desired state; controllers reconcile actual state to match. YAML files are how you express desired state.'),

        Card(topic='Kubernetes', difficulty='fundamental', card_type='scenario',
            front='Your Pod is in CrashLoopBackOff. Walk through how you diagnose it.',
            back='CrashLoopBackOff means the container is crashing repeatedly and k8s is backing off before restarting it.\n\n1. kubectl describe pod <name>  # check Events section for clues\n2. kubectl logs <name>          # read the crash output\n3. kubectl logs <name> --previous  # if current instance cannot start, read last crash\n4. Check: wrong command/args, missing env vars, missing ConfigMap/Secret, OOMKilled (memory limit hit)',
            why='CrashLoopBackOff is one of the most common Pod states you will see. The backoff is k8s protecting the cluster from a tight restart loop. --previous is the critical flag — the current pod may have no logs yet.',
            command='kubectl describe pod <name>\nkubectl logs <name> --previous'),


        # INTERMEDIATE

        Card(topic='Kubernetes', difficulty='intermediate', card_type='theory',
            front='What is a ConfigMap and when do you use it?',
            back='A ConfigMap stores non-sensitive configuration as key-value pairs. Injected into Pods as:\n- Environment variables\n- Files mounted into the container filesystem\n\nExample: app port, feature flags, database hostname (not password).\n\nConfigMaps are NOT encrypted. Never put passwords or tokens in a ConfigMap.',
            why='Separating config from the container image means you can change configuration without rebuilding the image. The same image runs in dev and prod with different ConfigMaps.'),

        Card(topic='Kubernetes', difficulty='intermediate', card_type='theory',
            front='What is a Secret and how does it differ from a ConfigMap?',
            back='A Secret stores sensitive data (passwords, tokens, TLS certificates) encoded in base64.\n\nDifferences from ConfigMap:\n- Stored separately in etcd\n- base64 encoded (NOT encrypted by default — still readable if you have cluster access)\n- Can be encrypted at rest with etcd encryption\n- RBAC can restrict who can read Secrets vs ConfigMaps\n\nbase64 is encoding, not encryption. Treat Secrets as sensitive but know their limits.',
            why='Kubernetes Secrets are frequently misunderstood. base64 is trivially reversible. Real secret management uses HashiCorp Vault or cloud provider KMS. Know the difference for interviews.'),

        Card(topic='Kubernetes', difficulty='intermediate', card_type='theory',
            front='What are labels and selectors and why do they matter?',
            back='Labels are key-value metadata attached to any Kubernetes resource (app: myapp, env: prod).\n\nSelectors filter resources by label. Services use selectors to find their target Pods.\n\nExample: A Service with selector app: myapp routes traffic to all Pods with label app: myapp — regardless of how many replicas or what their IPs are.',
            why='Labels are how Kubernetes resources refer to each other without hardcoding names. A Service does not care about Pod names or IPs — it cares about labels. This is what makes dynamic scaling work.'),

        Card(topic='Kubernetes', difficulty='intermediate', card_type='practice',
            front='How do you scale a Deployment and roll back a bad update?',
            back='# Scale\nkubectl scale deployment myapp --replicas=5\n\n# Rolling update (apply new image version)\nkubectl set image deployment/myapp myapp=myapp:v2\n\n# Check rollout status\nkubectl rollout status deployment/myapp\n\n# View history\nkubectl rollout history deployment/myapp\n\n# Rollback to previous version\nkubectl rollout undo deployment/myapp',
            why='Rollback is a one-command operation. This is one of the core selling points of Kubernetes over raw containers. In an interview, being able to describe this workflow shows you understand production operations.',
            command='kubectl rollout status deployment/myapp\nkubectl rollout undo deployment/myapp'),

        Card(topic='Kubernetes', difficulty='intermediate', card_type='theory',
            front='What is the difference between ClusterIP, NodePort, and LoadBalancer service types?',
            back='ClusterIP (default): only reachable within the cluster. Use for internal service-to-service communication.\n\nNodePort: exposes the service on a static port on every node (30000-32767). Accessible from outside the cluster via <NodeIP>:<NodePort>. How your home lab apps are reachable.\n\nLoadBalancer: provisions a cloud load balancer (AWS ELB, GCP LB). Only works on cloud providers or with MetalLB on bare metal.',
            why='NodePort is how you access your k3s apps from your LAN. ClusterIP is how microservices talk to each other inside the cluster. LoadBalancer is cloud production. Know which to use when.'),

        Card(topic='Kubernetes', difficulty='intermediate', card_type='theory',
            front='What are liveness and readiness probes?',
            back='Liveness probe: "Is this container still alive?" — if it fails, k8s restarts the container.\n\nReadiness probe: "Is this container ready to serve traffic?" — if it fails, k8s removes the Pod from the Service endpoints. Traffic stops going to it, but the container is not restarted.\n\nBoth can use HTTP GET, TCP socket, or exec (run a command).',
            why='A container can be alive but not ready (still initialising). Without a readiness probe, k8s sends traffic to a Pod that is not ready yet. This causes errors during deployments and restarts.'),

        Card(topic='Kubernetes', difficulty='intermediate', card_type='scenario',
            front='Your Deployment has 3 replicas but kubectl get pods shows only 2 Running and 1 Pending. What do you check?',
            back='Pending means the Pod has been accepted by the scheduler but cannot be placed on a node.\n\n1. kubectl describe pod <pending-pod>  # check Events: "Insufficient cpu", "Insufficient memory", "no nodes available"\n2. kubectl describe node <node>        # check Allocatable vs Requests\n3. kubectl get events                  # cluster-wide events\n\nCommon causes: resource limits too high, all nodes are full, node is NotReady (cordoned/tainted).',
            why='Pending is a scheduling problem, not an application problem. The container has not started yet. describe pod Events is always your first stop.',
            command='kubectl describe pod <pending-pod>\nkubectl describe node <node-name>'),


        # ADVANCED

        Card(topic='Kubernetes', difficulty='advanced', card_type='theory',
            front='What is Helm and what problem does it solve?',
            back='Helm is the package manager for Kubernetes. A Helm chart is a collection of YAML templates with configurable values.\n\nProblem solved: deploying a complex app (Postgres + app + ingress + secrets) requires many YAML files. Helm packages them into one chart with a values.yaml for customisation.\n\nhelm install myapp ./chart --set replicas=3',
            why='Most production software ships as Helm charts. Prometheus, cert-manager, nginx-ingress — all installed via Helm. Understanding charts and values.yaml is essential for Week 4+ work.'),

        Card(topic='Kubernetes', difficulty='advanced', card_type='theory',
            front='What is a StatefulSet and when do you use it instead of a Deployment?',
            back='StatefulSet is for stateful applications (databases) that need:\n- Stable, persistent hostnames (pod-0, pod-1, pod-2 — always the same names)\n- Stable, persistent storage (each Pod gets its own PVC)\n- Ordered startup and termination\n\nDeployment Pods are interchangeable. StatefulSet Pods have identity.\n\nUse StatefulSet for: Postgres, MySQL, Redis, Kafka, Elasticsearch.',
            why='Databases cannot be treated as interchangeable Pods — each node has its own data. StatefulSets ensure each Pod always gets the same storage and hostname, enabling proper cluster formation.'),

        Card(topic='Kubernetes', difficulty='advanced', card_type='theory',
            front='What is the difference between a DaemonSet and a Deployment?',
            back='Deployment: runs a specified number of Pod replicas, distributed across nodes.\n\nDaemonSet: runs exactly one Pod on every node (or a subset matching a selector). When new nodes join, DaemonSet automatically schedules a Pod on them.\n\nUse DaemonSet for: log collectors (Fluentd), monitoring agents (Prometheus node-exporter), network plugins.',
            why='DaemonSets are infrastructure-level workloads, not application workloads. If you are deploying Prometheus node-exporter (Week 7) to monitor all nodes, DaemonSet is the correct object.'),
    ]

    seed_topic('Kubernetes', kubernetes_cards)

    # ── LINUX ─────────────────────────────────────────────────────────────────

    linux_cards = [

        # FUNDAMENTAL

        Card(topic='Linux', difficulty='fundamental', card_type='practice',
            front='How do you navigate the filesystem and find what is in a directory?',
            back='pwd              # print working directory\nls               # list files\nls -la           # list all including hidden, with permissions\ncd /etc          # change to absolute path\ncd ..            # go up one level\ncd ~             # go to home directory\ntree /etc -L 2   # visual tree (2 levels deep)',
            why='These are muscle memory. ls -la is your default — it shows hidden files (dotfiles), permissions, owner, and size. You will use these hundreds of times per day.',
            command='ls -la\npwd\ncd /var/log'),

        Card(topic='Linux', difficulty='fundamental', card_type='practice',
            front='How do you read file contents and search inside them?',
            back='cat file.txt            # print entire file\nless file.txt           # paginated viewer (q to quit)\ntail -f /var/log/syslog # follow a log file live\nhead -n 20 file.txt     # first 20 lines\ngrep "error" file.txt   # search for pattern\ngrep -r "pattern" /etc  # recursive search in directory',
            why='tail -f is your live log viewer. grep is how you find things fast. In production you spend a lot of time reading logs — these commands are essential.',
            command='tail -f /var/log/syslog\ngrep -r "error" /var/log/'),

        Card(topic='Linux', difficulty='fundamental', card_type='theory',
            front='How do Linux file permissions work?',
            back='-rwxr-xr-- 1 rt rt 4096 file.txt\n\nBreakdown:\n- First char: - (file) d (directory) l (symlink)\n- rwx: owner permissions (read/write/execute)\n- r-x: group permissions\n- r--: others permissions\n\nchmod 755 file   # rwxr-xr-x\nchmod +x file    # add execute for all\nchown rt:rt file # change owner:group',
            why='Permissions cause many production issues. A script that works as root fails as a service account. A web server cannot read its config file. Understanding octal notation (755, 644) is essential.',
            command='ls -la\nchmod +x script.sh\nchown -R www-data:www-data /var/www'),

        Card(topic='Linux', difficulty='fundamental', card_type='practice',
            front='How do you manage running processes?',
            back='ps aux                  # all running processes\nps aux | grep nginx     # filter for a specific process\ntop                     # interactive process viewer (q to quit)\nhtop                    # better top (may need installing)\nkill <PID>              # send SIGTERM (graceful)\nkill -9 <PID>           # send SIGKILL (force kill)\npkill nginx             # kill by process name',
            why='kill sends SIGTERM by default — the process can catch it and clean up. -9 (SIGKILL) cannot be caught — the kernel terminates immediately. Always try SIGTERM first.',
            command='ps aux | grep python\nkill $(pgrep python)'),

        Card(topic='Linux', difficulty='fundamental', card_type='practice',
            front='How do you manage services with systemctl?',
            back='systemctl status nginx          # check if running\nsystemctl start nginx           # start\nsystemctl stop nginx            # stop\nsystemctl restart nginx         # stop + start\nsystemctl reload nginx          # reload config without restart\nsystemctl enable nginx          # start on boot\nsystemctl disable nginx         # do not start on boot\njournalctl -u nginx -f          # follow service logs',
            why='systemd is the init system on all modern Linux distros (Ubuntu, Debian, RHEL). journalctl -u <service> -f is your log viewer for system services — equivalent of docker logs for system processes.',
            command='systemctl status nginx\njournalctl -u nginx -f'),

        Card(topic='Linux', difficulty='fundamental', card_type='practice',
            front='How do you install packages and keep the system updated?',
            back='# Ubuntu/Debian (apt)\napt update                      # refresh package index\napt upgrade                     # upgrade all installed packages\napt install nginx               # install a package\napt remove nginx                # remove a package\napt search nginx                # search available packages\nwhich nginx                     # find where a binary is installed',
            why='apt update does NOT install anything — it just refreshes the list of available versions. You must run it before apt install to get the latest packages. Forgetting this is a common mistake.',
            command='apt update && apt install -y nginx'),

        Card(topic='Linux', difficulty='fundamental', card_type='theory',
            front='What is sudo and when do you need it?',
            back='sudo (superuser do) runs a command as root. Required for:\n- Installing packages\n- Modifying system files (/etc, /var)\n- Managing services\n- Changing network configuration\n\nsudo command         # run once as root\nsudo -i              # open a root shell (use carefully)\nwhoami               # check current user\nid                   # see user ID and group memberships',
            why='Running everything as root is dangerous — a mistake affects the entire system. sudo provides a controlled escalation with logging. In containers you often run as root; on host systems you should not.'),

        Card(topic='Linux', difficulty='fundamental', card_type='scenario',
            front='A service is not starting. Walk through your Linux diagnostic approach.',
            back='1. systemctl status <service>       # is it running? what is the error?\n2. journalctl -u <service> -n 50    # last 50 log lines\n3. journalctl -u <service> --since "5 minutes ago"  # recent logs\n4. ls -la /etc/<service>/           # check config file permissions\n5. <service> -t                     # test config syntax (nginx -t, apache2 -t)\n6. netstat -tlnp | grep <port>      # is something else using the port?',
            why='Systematic approach: status → logs → config → conflicts. Jumping to random fixes wastes time. The logs almost always tell you exactly what is wrong.',
            command='systemctl status nginx\njournalctl -u nginx -n 50\nnginx -t'),


        # INTERMEDIATE

        Card(topic='Linux', difficulty='intermediate', card_type='practice',
            front='How do you check disk, memory, and CPU usage?',
            back='df -h                   # disk free (human readable)\ndu -sh /var/log/*       # disk usage per directory\nfree -h                 # memory usage\nuptime                  # load averages (1m, 5m, 15m)\nnproc                   # number of CPU cores\ncat /proc/cpuinfo       # detailed CPU info\nvmstat 1 5              # system stats every 1s, 5 times',
            why='Load average > number of CPUs means the system is overloaded. free -h shows used vs available memory. These are the first commands when a server is slow.',
            command='df -h\nfree -h\nuptime'),

        Card(topic='Linux', difficulty='intermediate', card_type='practice',
            front='How do you use pipes and redirects to combine commands?',
            back='|   pipe: send output of one command to another\n>   redirect stdout to file (overwrites)\n>>  append stdout to file\n2>  redirect stderr to file\n2>&1 redirect stderr to same place as stdout\n\nExamples:\nps aux | grep nginx | wc -l    # count nginx processes\ncat /var/log/syslog | grep error > errors.txt\ndocker logs myapp > app.log 2>&1',
            why='Pipes are the Unix philosophy: small tools that do one thing, combined to solve complex problems. grep, awk, sort, wc, cut — mastering pipes lets you process any text output without writing scripts.',
            command='ps aux | grep -v grep | grep nginx\njournalctl -u nginx | grep -i error | tail -20'),

        Card(topic='Linux', difficulty='intermediate', card_type='practice',
            front='How do you use SSH to connect to and manage remote servers?',
            back='ssh user@192.168.0.21               # connect with password\nssh -i ~/.ssh/id_rsa user@host      # connect with key\nssh-keygen -t ed25519               # generate a key pair\nssh-copy-id user@192.168.0.21       # copy public key to server\n\n# Copy files remotely\nscp file.txt user@host:/tmp/\nrsync -av ./dir/ user@host:/remote/dir/',
            why='SSH keys are the standard for server access — never use passwords in production. ssh-copy-id sets up key auth in one command. rsync is smarter than scp — it only transfers changed files.',
            command='ssh-keygen -t ed25519 -C "home-lab"\nssh-copy-id rt@192.168.0.21'),

        Card(topic='Linux', difficulty='intermediate', card_type='practice',
            front='How do you find files on the filesystem?',
            back='find / -name "nginx.conf"              # find by name\nfind /etc -name "*.conf" -type f       # conf files only\nfind /var/log -mtime -1                # modified in last 24h\nfind / -size +100M                     # files larger than 100MB\nlocate nginx.conf                      # faster (uses index, may be stale)\nwhich python3                          # find binary in PATH',
            why='find is powerful but slow on large filesystems (scans in real time). locate is fast but requires updatedb to have run recently. which is instant for finding executables.',
            command='find /etc -name "*.conf" -type f\nfind /var/log -mtime -1 -name "*.log"'),
    ]

    seed_topic('Linux', linux_cards)

    # ── NETWORKING ────────────────────────────────────────────────────────────

    networking_cards = [

        # FUNDAMENTAL

        Card(topic='Networking', difficulty='fundamental', card_type='theory',
            front='What is an IP address and what is the difference between IPv4 and IPv6?',
            back='An IP address is a unique identifier for a device on a network.\n\nIPv4: 32-bit, written as 4 octets — 192.168.0.1. ~4.3 billion addresses (exhausted).\nIPv6: 128-bit, written in hex — 2001:db8::1. Effectively unlimited.\n\nPrivate IPv4 ranges (not routable on internet):\n10.0.0.0/8\n172.16.0.0/12\n192.168.0.0/16  ← your home lab',
            why='Your home lab uses 192.168.0.x — a private range. These IPs never appear on the internet. NAT at your router translates them to your public IP when reaching external services.'),

        Card(topic='Networking', difficulty='fundamental', card_type='theory',
            front='What is CIDR notation and how do you read a subnet mask?',
            back='CIDR (Classless Inter-Domain Routing) notation: IP/prefix-length\n\n192.168.0.0/24 means:\n- Network: 192.168.0.0\n- /24 = 24 bits for network, 8 bits for hosts\n- 256 addresses, 254 usable (0 = network, 255 = broadcast)\n\n/16 = 65,536 addresses\n/24 = 256 addresses\n/32 = single host',
            why='You need to read CIDR notation to understand Docker networks, Kubernetes pod CIDRs, VPC subnets, and firewall rules. /24 is the most common home/office subnet.'),

        Card(topic='Networking', difficulty='fundamental', card_type='theory',
            front='What is DNS and how does it work?',
            back='DNS (Domain Name System) translates human-readable names to IP addresses.\n\nFlow: your browser asks "what is the IP of google.com?"\n1. Check local cache\n2. Ask your configured DNS resolver (e.g. 8.8.8.8)\n3. Resolver queries root → TLD (.com) → authoritative nameserver\n4. Returns IP address\n5. Browser connects to that IP\n\nnslookup google.com\ndig google.com',
            why='DNS problems look like connectivity problems. "Cannot reach service" is often "cannot resolve hostname." Always check DNS resolution before assuming network failure.',
            command='nslookup google.com\ndig google.com\ndig @8.8.8.8 google.com'),

        Card(topic='Networking', difficulty='fundamental', card_type='theory',
            front='What is a port and why do applications use specific ones?',
            back='A port is a number (0-65535) that identifies a specific process on a machine. IP routes to the machine, port routes to the application.\n\nWell-known ports:\n22  SSH\n80  HTTP\n443 HTTPS\n5432 PostgreSQL\n6443 Kubernetes API server\n\nYour apps: 5001, 5002, 5003 (custom, avoids conflicts with system services)',
            why='When you docker run -p 8080:80, you are mapping host port 8080 to container port 80. Port conflicts (EADDRINUSE) happen when two processes try to bind the same port.'),

        Card(topic='Networking', difficulty='fundamental', card_type='practice',
            front='How do you test network connectivity from the command line?',
            back='ping 8.8.8.8                    # ICMP reachability test\nping google.com                 # also tests DNS resolution\ncurl http://192.168.0.24:5001  # test HTTP endpoint\ncurl -I https://google.com      # headers only (fast check)\nwget http://url -O /dev/null    # download to /dev/null (test speed)\ntelnet 192.168.0.21 22          # test if TCP port is open',
            why='ping tests reachability. curl tests the actual application endpoint. If ping works but curl fails, the app is the problem. If ping fails, the network is the problem. Isolate layers.',
            command='ping -c 3 8.8.8.8\ncurl -I http://192.168.0.24:5001\n'),

        Card(topic='Networking', difficulty='fundamental', card_type='practice',
            front='How do you see what ports are open and what is listening on them?',
            back='ss -tlnp                        # TCP listening ports + process\nss -ulnp                        # UDP listening ports\nnetstat -tlnp                   # older equivalent (may not be installed)\nlsof -i :5001                   # what is using port 5001\nkubectl get svc                 # services exposed in Kubernetes',
            why='ss is the modern replacement for netstat. -t=TCP -l=listening -n=numeric ports -p=show process. Essential for debugging "address already in use" errors.',
            command='ss -tlnp\nlsof -i :5001'),

        Card(topic='Networking', difficulty='fundamental', card_type='theory',
            front='What is the difference between TCP and UDP?',
            back='TCP (Transmission Control Protocol):\n- Connection-oriented (3-way handshake)\n- Guaranteed delivery, ordered packets\n- Error checking and retransmission\n- Use for: HTTP, SSH, databases, file transfer\n\nUDP (User Datagram Protocol):\n- Connectionless, fire-and-forget\n- No guarantee of delivery or order\n- Lower latency\n- Use for: DNS, video streaming, gaming, metrics (StatsD)',
            why='Most DevOps services use TCP. DNS uses UDP (fast queries). Understanding this helps debug firewall rules — you may need to open both TCP and UDP ports for some services.'),


        # INTERMEDIATE

        Card(topic='Networking', difficulty='intermediate', card_type='theory',
            front='What is NAT and how does it relate to your home lab?',
            back='NAT (Network Address Translation) allows multiple devices with private IPs to share one public IP.\n\nYour home lab flow:\n- Devices have private IPs: 192.168.0.x\n- Your router has one public IP from your ISP\n- Outbound: router rewrites source IP to public IP\n- Inbound: port forwarding rules direct traffic to internal hosts\n\nYour apps are accessible on your LAN but not from the internet (unless you set up port forwarding).',
            why='Understanding NAT explains why your home lab apps are only accessible on 192.168.0.x. Port forwarding on your router would expose them externally — but also exposes them to the internet.'),

        Card(topic='Networking', difficulty='intermediate', card_type='theory',
            front='What is a firewall and how does UFW work on Ubuntu?',
            back='A firewall controls which network traffic is allowed in/out based on rules (IP, port, protocol).\n\nUFW (Uncomplicated Firewall) on Ubuntu:\nufw status                      # is it active?\nufw allow 22/tcp                # allow SSH\nufw allow 5001/tcp              # allow your app\nufw deny 5432/tcp               # block postgres from outside\nufw enable\nufw delete allow 5001/tcp       # remove a rule',
            why='If you can ping a server but cannot connect to your app, the firewall is blocking the port. UFW is the friendly frontend to iptables. Always allow SSH (22) before enabling the firewall or you will lock yourself out.',
            command='ufw status verbose\nufw allow 22/tcp\nufw allow 5001/tcp'),

        Card(topic='Networking', difficulty='intermediate', card_type='practice',
            front='How do you trace the network path to a destination?',
            back='traceroute 8.8.8.8              # show each hop to destination\nmtr 8.8.8.8                    # real-time traceroute (better tool)\ncurl -v http://192.168.0.24:5001  # verbose curl shows DNS + TCP handshake\ndig +trace google.com           # trace DNS resolution step by step\nkubectl exec pod -- curl http://service-name  # test internal k8s DNS',
            why='When a connection fails, traceroute shows where it breaks. In Kubernetes, testing connectivity from inside a Pod (kubectl exec + curl) isolates whether it is a network policy, DNS, or application issue.',
            command='traceroute 8.8.8.8\nkubectl exec -it <pod> -- curl http://my-service:5000'),

        Card(topic='Networking', difficulty='intermediate', card_type='scenario',
            front='Your app is running in Kubernetes but you cannot reach it from your laptop. Walk through diagnosing it.',
            back='Layer by layer:\n1. kubectl get pods             # is the pod running?\n2. kubectl get svc              # is the Service created? correct type (NodePort)?\n3. kubectl describe svc myapp  # what port is it on?\n4. curl http://<node-ip>:<nodeport>  # test from laptop\n5. kubectl exec pod -- curl localhost:5000  # test inside pod\n6. kubectl logs pod            # any app errors?\n7. Check firewall on the node: ufw status',
            why='Work from the inside out: app → Pod → Service → Node → network. If it works inside the Pod but not from outside, the issue is Service/NodePort config or firewall. This systematic approach finds the layer where it breaks.',
            command='kubectl get svc\nkubectl describe svc myapp\ncurl http://192.168.0.21:30080'),
    ]

    seed_topic('Networking', networking_cards)


# ─── Init ────────────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()
    seed_database()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
