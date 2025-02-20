## 2.0.2

#### Enhancements made

- Updated to otter-grader 6.0.4
## 1.1.1

#### Enhancements made

- Remove OAuth

## 1.1.0

#### Enhancements made

- Updated Grade reporting to three decimals

## 0.2.10

#### Enhancements made

- otter-service handles any course from edx with appropriate config
- changes to how secrets are stored
- updates to logging

## 0.2.4

#### Enhancements made

- Ubuntu 22.04
- Cleaning OAuth, tornado libraries
- Flake8 Lint cleanUp
- Updated route to /services/otter_grade


## 0.1.75.13

#### Enhancements made

- cycled gh key

## 0.1.22

#### Enhancements made

- Changed the error handling on the GradePostException
- Changed deletion of materials directory to just before downloading

## 0.1.21

#### Enhancements made

- Save_Path are trailing forward slash

## 0.1.20

#### Enhancements made

- Fixed URI to include backslash

## 0.1.19

#### Enhancements made

- Configured the grading to download autotgrader materials each time so
that the materials can be changed and the system not re-deployed
- fixed image name in deployment.yaml; mistake in set-image path

## 0.1.18

#### Enhancements made

- cloud deploy not longer dependent on local build

## 0.1.17

#### Enhancements made

- deploys from branches to appropriate namespaces
- converted to otter-service(removed from gofer-service repo)

## 0.1.11

#### Enhancements made

- Configure GitHub Actions: releases, deployments
- Added init.py to src dir to run pytests from GH
- arrange test files Github Action to run tests
- Github Action configured to build off master
- Github Action configured to build docker image
- Github Action configured to push docker image and deploy to cluster
- Added Persistent Volume
- Added NFS


## 0.1

### 0.1.0 - 2021-10-23

#### Enhancements made

- swapped gofer-grader to otter-grader

#### Bugs fixed

- improved error handling to ensure we don't try to post a bad submission
