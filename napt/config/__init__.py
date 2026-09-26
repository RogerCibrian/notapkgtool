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

"""Configuration loading and management for NAPT.

Loads and merges YAML configuration in five layers: code defaults,
defaults/org.yaml, defaults/vendors/{Vendor}.yaml, the parent recipe, and the
recipe.

The loader performs deep merging where dicts are merged recursively and
lists/scalars are replaced (last wins). See the Path resolution section of
[loader][napt.config.loader] for how relative paths resolve.

Modules:
    loader: The layered configuration loader (load_effective_config).
    defaults: Built-in default configuration and the org.yaml template.
"""
