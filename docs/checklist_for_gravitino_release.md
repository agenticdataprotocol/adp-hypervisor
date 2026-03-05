# Checklists for releasing a version

# Checklists for a release

## Before release: 

- Raise a PR to support auto cherry pick for the release version, please see the file: `.github/workflows/auto-cherry-pick.yml.`(Minor release can skip this step)  
- Cut branch(minor release can skip this step), the branch name is like branch-1.2  
- Organize issues and add necessary tags for this release. Tips: We need to make sure all features have been completed.  
- Check and refine the license of jars introduced in this version.  
- Update the latest version in `docs/docker-image-details.md`  
- Prepare the release note.  
- Check docs: Whether new docs have been added, whether we need to adjust the structure of the docs (cooperate with frontend)

## During release:

- Run `dev/release/do-release.sh` to release a candidate, **When you run do-release.sh, you need to create a new directory such as rc1, rc2, etc., then copy dev/release into that directory and run the script.**  
-   
- Verify the release result, including: Apache Maven repo, PyPI, and download the release tarball to verify it works  
- Use the playground to verify Gravitino  
- Use GitHub CI runner to release a Docker image  
- Call for a vote on the release candidate.

## After release:

- After everything is okay(vote pass),  run `do-release.sh finalize` to formally release the candidate.  
- Download the tarball to verify it again.  
- Close the Apache Maven repo and release it  
- Update the version in the Gravitino playground  
- Add release note to Gravitino-web and GitHub  
- Announce the release on WeChat, Slack group, and the ASF mailing list.  
- Update Gravitino main to the next snapshot, for example, if 1.2.0 has been successfully released, then we need to update the version to \`1.3.0-snapshot\`. 

# How to run [`do-release.sh`](http://do-release.sh) to release a version

## Start a Linux VM in GCP

Install commands such as svn,gpg, and then generate a GPG key. More commands, please review the shell scripts.

## Upload GPG key.

Upload a GPG key to [https://dist.apache.org/repos/dist/dev/gravitino/KEYS](https://dist.apache.org/repos/dist/dev/gravitino/KEYS) to prepare for releasing a new version

| svn checkout [https://dist.apache.org/repos/dist/dev/gravitino](https://dist.apache.org/repos/dist/dev/gravitino) cd gravitino vim KEYS or cat mykey.asc \>\> KEYS svn commit \-m "Add GPG key for \<your name\>" |
| :---- |

Then you can see the keys in [https://dist.apache.org/repos/dist/dev/gravitino/KEYS](https://dist.apache.org/repos/dist/dev/gravitino/KEYS) via browser

The last steps: Upload your public key to [http://keyserver.ubuntu.com](http://keyserver.ubuntu.com). Apache Maven repo will use it to sign the jars published to it. 

## Familiarizing and testing the release scripts

Please install the required command before running [`do-release.sh`](http://do-release.sh). （make sure the branch exists in the github repo) The required commands are

- zip & unzip  
- subversion  
- java  
- twine  
- make  
- git

and the required environments:

export PYPI\_API\_TOKEN='pypi-AgEIcHlwaS5vcmcCJGYzNDE4YTg3LWEyMTctNGVlNS1iNzZhLTc1NmI5ZDBjNzhlZgACKlszLCIyYjcyZjFjMi01MTc3LTRjMmMtYTJlMi04YzhjMmY4OTM5NjYiXQAABiCoodMQs\_Au129Neb7lYCHZCszOunx9ZvVNazX-avzQeA'  
export ASF\_USERNAME='xxxx' (Apache account, without @apache.org)  
export ASF\_PASSWORD='xxxx' (Apache account password)

If you run into some problems with git, you may need to add the following command

\`\`\`  
git config \--global http.version HTTP/1.1  
git config \--global http.maxRequests 1  
\`\`\`

Then run \`[do-release.sh](http://do-release.sh)\` and input the information as it suggests. Please watch the log and debug it if an error happens.

## Release several RC candidates

If all necessary commits have been included in the branch, you can launch a new release candidate and call for a release vote. 

Before the release vote, please make sure

- [`do-release.sh`](http://do-release.sh) was called successfully  
- Release the Docker image via GitHub CI action.

This is an example of the content of a vote call:   
[https://lists.apache.org/thread/yddh62dnnnpfqbc5jy1bjo68dl89q6bv](https://lists.apache.org/thread/yddh62dnnnpfqbc5jy1bjo68dl89q6bv)

For the last candidate, it is possibly the formal release one, so you may need to 

- Check that the release tar files work well. (make sure Gravitino and Graviitno-playground work well)  
- Running `./do_release.sh finalize` to release the last rc  

Java package

- Log in to [https://repository.apache.org/](https://repository.apache.org/) and close the staging repo with your Apache account, and find them in the [Staging Repositories](https://repository.apache.org/#)  
- Release the staging one

Python package

- Review [https://pypi.org/project/apache-gravitino/1.2.0rcx/](https://pypi.org/project/apache-gravitino/1.2.0rcx/)

Gravitino package

- Review [https://github.com/apache/gravitino/releases/tag/](https://github.com/apache/gravitino/releases/tag/v1.1.0-rc4)  
- [https://dist.apache.org/repos/dist/dev/gravitino/v1.1.0-rc4/](https://dist.apache.org/repos/dist/dev/gravitino/v1.1.0-rc4/)

# How to Raise PR to the Gravitino web

For more information, please refer to [https://github.com/apache/gravitino-site/pull/100](https://github.com/apache/gravitino-site/pull/100) and [https://github.com/apache/gravitino-site/pull/104](https://github.com/apache/gravitino-site/pull/104)

# How to add release information in GitHub

Please refer to [https://github.com/apache/gravitino/releases](https://github.com/apache/gravitino/releases)

# How to announce the release

Announce the release in the following channel: 

- Wechat group  
- Slack group  
- Apache mail, more please refer to [https://lists.apache.org/thread/pxvjzpwgs1cz20c9v7r5btbqkgrjhg9d](https://lists.apache.org/thread/pxvjzpwgs1cz20c9v7r5btbqkgrjhg9d)  
- Linkin(Guoyue’s work?)

