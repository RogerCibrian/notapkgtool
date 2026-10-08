# Copyright 2025 Roger Cibrian
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Recipes imported from other git repositories.

A project imports a recipe with ``napt upstream add``, which vendors a
byte-identical copy under ``upstream/<host>/<repo path>/<path>``, writes an
override in ``recipes/`` that names the copy as its ``parent``, and records
the copy's hashes in ``upstream.yaml`` at the project root. The config
loader treats every parent under ``upstream/`` as foreign: the file must
match its recorded hash, and only app-owned keys reach the merge.

Modules:
    lock: The ``upstream.yaml`` lockfile, canonical hashing, and the
        directory a repository URL vendors into.
    vendored: What makes a parent foreign, the hash check, and the keys a
        foreign parent may set.
"""
