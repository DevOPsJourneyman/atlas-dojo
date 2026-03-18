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

New topics added weekly as the roadmap progresses (Kubernetes → Ansible → Terraform → CI/CD → Monitoring).

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
git clone https://github.com/DevOpsJourneyman/atlas-dojo
cd atlas-dojo
docker compose up -d --build
```

App runs at `http://192.168.0.24:5002`

## Tech Stack

- Python / Flask
- SQLite via SQLAlchemy
- SM-2 spaced repetition algorithm
- Docker + Docker Compose
- Ubuntu Server VM on Proxmox (Atlas Lab)

## Part of the DevOps Roadmap

**Week:** 2 — Docker Fundamentals  
This project reinforces the same Docker patterns as the nutrition tracker (Week 2 deliverable #1) through deliberate repetition with a different data model.
