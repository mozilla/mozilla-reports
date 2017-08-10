# The Knowledge Repository

## Introduction

The Knowledge Repository project is focussed on facilitating the sharing of knowledge between data scientists and other technical roles using data formats and tools that make sense in these professions. It provides various data stores (and utilities to manage them) for "knowledge posts". These knowledge posts are a general markdown format that is automatically generated from the following common formats:

 - Jupyter/Ipython notebooks
 - Rmd notebooks
 - Markdown files

The Jupyter, Rmd, and Markdown files are required to have a specific set of yaml style headers which are used to organize and discover research:

```
---
title: I Found that Lemurs Do Funny Dances
authors:
- sally_smarts
- wesley_wisdom
tags:
- knowledge
- example
created_at: 2016-06-29
updated_at: 2016-06-30
tldr: This is short description of the content and findings of the post.
---
```

Users add these notebooks/files to the knowledge repository through the `knowledge_repo` tool, as described below; which allows them to be rendered and curated in the knowledge repository's web app.

## Getting started

### Installation
To install the knowledge repository tooling, simply run:

`pip install git+ssh://git@github.com/airbnb/knowledge-repo.git`

## Writing Knowledge Posts

### TLDR Guide For Contributing

Here is a snapshot of the commands you need to run to upload your own knowledge post.

0. Create a new report starting from the "New Report" template available on a newly launched a.t.m.o. cluster.
1. Download the report on your machine (e.g. `~/Documents/my_post.ipynb`).
2. Add yaml style headers to your report as described [here](https://github.com/airbnb/knowledge-repo#introduction).
3. `git clone` this knowledge repository.
4. Set the `$KNOWLEDGE_REPO` environment variable to the location of the knowledge repository.
5. `knowledge_repo add ~/Documents/my_post.ipynb -p projects/test_project`
6. `knowledge_repo preview projects/test_project`
7. `knowledge_repo submit projects/test_project`
8. Open a PR in GitHub
9. After it has been reviewed, merge it in to master.

## Technical Details

### What is a Knowledge Repository

A knowledge repository is a virtual filesystem (such as a git repository or database). A GitKnowledgeRepository, for example, has the following structure:

	<repo>
	    + .git  # The git repository metadata
	    + .resources  # A folder into which the knowledge_repo repository is checked out (as a git submodule)
	    - .knowledge_repo_config.py  # Local configuration for this knowledge repository
	    - <knowledge posts>

The use of a git submodule to checkout the knowledge_repo into `.resources` allows use to ensure that the client and server are using the same version of the code. When one uses the `knowledge_repo` script, it actually passes the options to the version of the `knowledge_repo` script in `.resources/scripts/knowledge_repo`. Thus, updating the version of knowledge_repo used by client and server alike is as simple as changing which revision is checked out by git submodule in the usual way. That is:

	pushd .resources
	git pull
	git checkout <revision>/<branch>
	popd
	git commit -a -m 'Updated version of the knowledge_repo'
	git push

Then, all users and servers associated with this repository will be updated to the new version. This prevents version mismatches between client and server, and all users of the repository.

In development, it is often useful to disable this chaining. To use the local code instead of the code in the checked out knowledge repository, pass the `--dev` option as:

`knowledge_repo --repo <repo_path> --dev <action> ...`

### What is a Knowledge Post?

A knowledge post is a virtual directory, with the following structure:

	<knowledge_post>
		- knowledge.md
		+ images/* [Optional]
		+ orig_src/* [Optional; stores the original converted file]

