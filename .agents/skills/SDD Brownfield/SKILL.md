We are adopting Spec-Driven Development in this existing project.

Do not rewrite or refactor the application yet.

First inspect and understand the existing codebase.

Read and analyze:
- implementation_plan.md
- TASK_PLAN.md

and create new `spec/` directory with full spec documents.

This includes:
- mission.md is about :


WHAT?

what the product?

WHY?

why we build this product?

WHO?

who is the target users?

SCOPE?

what is the scope?

Example:

# Mission

## Product
TaskFlow is a task management web application.

## Problem
Small teams need a simple way to track tasks
without the complexity of enterprise project-management tools.

## Target Users
Small software teams.

## Core Goal
Allow users to create, assign, track, and complete tasks.

## Scope
The MVP will support:
- User accounts
- Projects
- Tasks
- Task status
- tech.md
- roadmap.md
- architecture.md
- flows.md
- test.md

Tech Stack.md :is aout the technologies that will be used in the project.

Architectural Invariants are the rules that must be followed in the project.

for example 

# Tech Stack

## Frontend
- React
- TypeScript

## Backend
- Node.js
- TypeScript

## Database
- SQLite
- Prisma

## Testing
- Vitest

## Deployment
- Docker


Roadmap.md :is about the roadmap of the project. and it is divided into phases.

for example:
# Roadmap

## Phase 1
1. Project setup
2. Homepage
3. Task creation

## Phase 2
4. Authentication
5. Task assignment
6. Task filtering

## Phase 3
7. Notifications
8. Analytics

## Architecture

This project follows a modular architecture with the following key components:

- **Core**: Contains the main application logic and business rules.
- **Utils**: Reusable utility functions and helpers.
- **Storage**: Data storage and retrieval mechanisms.
- **Web**: Web-specific components and interfaces.



