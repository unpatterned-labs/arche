# Copyright 2026 unpatterned.org
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

"""Geo enrichment for resolution — the ``arche-core[geo]`` layer.

Point-in-polygon reverse geocoding (``annotate_admin``) and (later) Overture
Places ingestion. Needs ``shapely`` (+ ``duckdb`` for Overture); install with
``pip install arche-core[geo]``. H3 spatial *blocking* stays in the base wheel
(``arche.resolve._block``) — only polygon joins live here.
"""

from arche.resolve._geo.annotate import AdminIndex, annotate_admin

__all__ = ["AdminIndex", "annotate_admin"]
