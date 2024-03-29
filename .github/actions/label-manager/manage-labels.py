#!/usr/bin/python3
# based on
# https://github.com/actions-automation/manage-your-labels
# base commit:
# https://github.com/actions-automation/manage-your-labels/commit/08ca6a139b807f638d2f40826a805321d5a4187d
# released under
# Apache License 2.0
# changes:
# - config yml schema
# - action inputs
# - allow on push,
from githubgql import githubgql

import sys
import os
import yaml

QUERY = '''
query($owner:String!, $reposCursor:String, $labelsCursor:String) {
    organization(login:$owner) {
        repositories(first:100, after:$reposCursor) {
            pageInfo { endCursor hasNextPage }
            nodes {
                name
                id
                labels(first:100, after:$labelsCursor) {
                    pageInfo { endCursor hasNextPage }
                    nodes {
                        name
                        id
                        color
                        description
                    }
                }
            }
        }
    }
}
'''

cursors = {
    "reposCursor": {
        'path': ["organization", "repositories"],
        'next': {
            "labelsCursor": ["labels"]
        }
    }
}

UPDATE_LABEL = '''
mutation($input: UpdateLabelInput!) {
    updateLabel(input: $input) {
        __typename
    }
}
'''

CREATE_LABEL = '''
mutation($input: CreateLabelInput!) {
    createLabel(input: $input) {
        __typename
    }
}
'''

DELETE_LABEL = '''
mutation($input: DeleteLabelInput!) {
    deleteLabel(input: $input) {
        __typename
    }
}
'''

owner, repo = os.environ["GITHUB_REPOSITORY"].split("/")

if repo != ".github":
    print("""
Label management must be performed from your user or organization's .github
repo. If already enabled there, no more action is necessary.
    """)
    sys.exit(1)

# Get Github token.
token = sys.argv[2]

# Open label data from the .github repository.
with open(sys.argv[1]) as f:
    input = yaml.safe_load(f)

GROUPS = input["groups"]
REPOS = input["repositories"]

# Fetch repository data.
try:
    result = githubgql.graphql(QUERY, token=token, cursors=cursors, owner=owner)
except githubgql.TokenError as e:
    print(e.error)
    sys.exit(0)

print()
print(" --- STARTING LABEL SYNC --- ")
print()

# Iterate through all repos controlled by the owner.
for repo in result["organization"]["repositories"]["nodes"]:
    # Construct the set of labels that should be on this repo.

    # only run it on enabled repos
    if repo['name'] not in REPOS:
        continue

    current_labels = {}
    try:
        for group in REPOS[repo['name']]:
            current_labels.update(GROUPS[group])
    except:
        pass
    current_labels.update(GROUPS["default"])
    current_labels_names = {l for l in current_labels.keys()}

    # Get the existing set of labels on the repo.
    existing_labels = {l["name"]: l for l in repo["labels"]["nodes"]}
    existing_labels_names = {l for l in existing_labels.keys()}

    # Construct a dictionary of old label names and their new names to be used
    # in renaming.
    all_old_names = {}
    for k in current_labels_names:
        for old_name in current_labels[k].get('old_names', []):
            all_old_names[old_name] = k

    # Find the set of labels on the repo that need to be renamed.
    to_be_renamed = existing_labels_names & all_old_names.keys()

    # Rename, if there are labels to be renamed.
    if len(to_be_renamed) > 0:
        for name in to_be_renamed:
            print(f"{owner}/{repo['name']}: renaming label {name} to {all_old_names[name]}")
            try:
                githubgql.graphql(UPDATE_LABEL, token=token, accept="application/vnd.github.bane-preview+json", input={
                        "id": existing_labels[name]["id"],
                        "name": all_old_names[name]
                    }
                )
            except githubgql.GraphQLError as e:
                if(e.errors[0]['type'] == "FORBIDDEN"):
                    print(f"Cannot edit labels on {repo['name']}. Please ensure bot has permission to create and edit labels.")
                    continue
                else:
                    raise

        # To prevent actions being taken on stale fetch data, defer
        # further processing after renames happen (if they happen).
        REPOS[repo['name']]

    # Construct sets of label names to use in processing.
    labels_to_add = current_labels_names - existing_labels_names
    labels_to_delete = existing_labels_names - current_labels_names
    common_labels = existing_labels_names & current_labels_names

    # Construct the set of common labels that need editing.
    labels_to_edit = set()
    for name in common_labels:
        color = existing_labels[name]["color"] != current_labels[name]['color']
        description = existing_labels[name]["description"] != current_labels[name]['description']

        if color or description:
            labels_to_edit.add(name)

    # Print status before performing any changes
    print(f"{owner}/{repo['name']}:", end="")
    for label in sorted(current_labels_names | existing_labels_names):
        state = ""
        if label in labels_to_add:
            state = "+"
        if label in labels_to_delete:
            state = "-"
        if label in labels_to_edit:
            state = "*"
        print(f" {state}{label}", end="")
    print()

    # Add new labels, and delete unused ones.
    for name in labels_to_add:
        label_to_create = current_labels[name]
        try:
            githubgql.graphql(CREATE_LABEL, token=token, accept="application/vnd.github.bane-preview+json", input={
                    "repositoryId": repo["id"],
                    "name": name,
                    "color": label_to_create['color'].replace("'", ""),
                    "description": label_to_create['description']
                }
            )
        except githubgql.GraphQLError as e:
            if(e.errors[0]['type'] == "FORBIDDEN"):
                print(f"Cannot edit labels on {repo['name']}. Please ensure bot has permission to create and edit labels.")
                continue
            else:
                raise
    for name in labels_to_delete:
        id_to_delete = existing_labels[name]["id"]
        try:
            githubgql.graphql(DELETE_LABEL, token=token, accept="application/vnd.github.bane-preview+json", input={
                    "id": id_to_delete
                }
            )
        except githubgql.GraphQLError as e:
            if(e.errors[0]['type'] == "FORBIDDEN"):
                print(f"Cannot edit labels on {repo['name']}. Please ensure bot has permission to create and edit labels.")
                continue
            else:
                raise

    # If a label needs to be edited, perform the edit.
    for name in labels_to_edit:
        try:
            githubgql.graphql(UPDATE_LABEL, token=token, accept="application/vnd.github.bane-preview+json", input={
                    "id": existing_labels[name]["id"],
                    "name": name,
                    "color": current_labels[name]["color"].replace("'", ""),
                    "description": current_labels[name]['description']
                }
            )
        except githubgql.GraphQLError as e:
            if(e.errors[0]['type'] == "FORBIDDEN"):
                print(f"Cannot edit labels on {repo['name']}. Please ensure bot has permission to create and edit labels.")
                continue
            else:
                raise

print()
print(" --- LABEL SYNC COMPLETE --- ")
print()
