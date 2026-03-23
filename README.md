[![CI](https://github.com/DevOPsJourneyman/atlas-dojo/actions/workflows/ci.yml/badge.svg)](https://github.com/DevOPsJourneyman/atlas-dojo/actions/workflows/ci.yml)
# Atlas Dojo

> *Every master built their edge in the quiet hours. Commit. Push. Deploy. Repeat.*

A spaced repetition training tool for DevOps engineers. Built with Flask + SQLite, containerised with Docker, deployed on a self-hosted Proxmox home lab.

## What It Does

- **Daily Review** — Anki-style spaced repetition. Cards surface based on how well you know them. Rate each card: Again / Hard / Good / Easy. The algorithm schedules the next review automatically.
- **Lab Scenarios** — Real diagnostic scenarios. Read the problem, think through the approach, reveal the solution and commands.
- **Browse All** — Full card library with filters by topic, difficulty, and type. See your progress per card.

## Card Library

| Topic | Difficulty | Types |
|---|---|---|
| Docker | Fundamental | Theory, Practice, Why, Scenario |
| Docker | Intermediate | Theory, Practice, Why, Scenario |
| Docker | Advanced | Theory, Practice, Why |
| GitHub | Fundamental | Theory, Practice, Why, Scenario |
| GitHub | Intermediate | Theory, Practice, Why, Scenario |

New topics added weekly as the roadmap progresses (Ansible → Terraform → Monitoring).

## Spaced Repetition Algorithm

Based on SM-2 (the same algorithm Anki uses):

| Rating | Next Review | Effect |
|---|---|---|
| Again | Tomorrow | Ease factor decreases, streak resets |
| Hard | 1-2 days | Ease factor decreases slightly |
| Good | 3+ days | Normal progression |
| Easy | 7+ days | Ease factor increases |

## Quick Start

```bash
docker pull devopsjourneyman/atlas-dojo:latest
docker run -d -p 5002:5000 -v dojo_data:/data devopsjourneyman/atlas-dojo:latest
```

Open `http://localhost:5002`

## Running on Home Lab
```bash
kubectl apply -f kubernetes/
```

See [atlas-lab](https://github.com/DevOpsJourneyman/atlas-lab) for infrastructure details.

## Tech Stack

- Python / Flask
- SQLite via SQLAlchemy
- SM-2 spaced repetition algorithm
- Docker + Docker Compose
- Kubernetes (k3s) — Deployment, Service, PersistentVolumeClaim
- GitHub Actions — CI/CD pipeline (lint → build → smoke test → push)
- Ubuntu Server VMs on Proxmox (Atlas Lab)

## CI/CD Pipeline

Automated via GitHub Actions on every push:

1. **Lint** — Dockerfile analysed with hadolint
2. **Build & Test** — image built, container started, smoke tested with curl
3. **Push** — verified image pushed to Docker Hub

Each job only runs if the previous one passes.

## Part of the DevOps Roadmap

**Weeks:** 2 (Docker) · 3–4 (Kubernetes) · 5–6 (CI/CD)  
Portfolio goal: Demonstrate containerisation, Kubernetes deployment, and automated CI/CD pipeline on a real self-hosted application.
