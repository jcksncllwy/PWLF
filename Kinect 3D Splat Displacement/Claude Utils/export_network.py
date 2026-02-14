"""
Export TouchDesigner network to compact JSON for Claude Code review.

Run from a Text DAT: right-click -> Run Script (or Ctrl+R)

Only exports /GaussianSplatting (the actual project), skipping TD system
nodes (/ui, /sys, /local). Captures real parameter values instead of
useless TDJSON page references.

Built-in component internals (Annotate, Window, etc.) are collapsed to
just their custom parameters -- their internal UI nodes are skipped.

Outputs to: [project folder]/Claude Utils/network_export.json
"""

import json

# Which subtrees to export (add more paths if needed)
EXPORT_ROOTS = ['/GaussianSplatting']

# Skip parameters that are at their default values to reduce noise
SKIP_DEFAULTS = True

# Max recursion depth
MAX_DEPTH = 8

# Operator types whose children are internal UI -- skip recursing into them.
# We still capture their custom parameters and title/body text.
COLLAPSE_TYPES = {'annotate', 'window', 'opviewer', 'field'}

# Built-in parameter pages that are rarely useful for understanding the network.
# Custom pages are always included.
SKIP_PAGES = {
	'Layout', 'Panel', 'Look', 'Children', 'Drag/Drop', 'Extensions',
	'OP Viewer', 'About', 'Settings', 'Dragger', 'Internal',
}


def serialize_op(operator, depth=0):
	if depth > MAX_DEPTH:
		return None

	op_type = operator.type

	node = {
		'name': operator.name,
		'type': op_type,
		'family': operator.family,
	}

	# For collapsed types, just capture key info and skip children
	if op_type in COLLAPSE_TYPES:
		_add_collapsed_info(node, operator)
		return node

	# Serialize non-default parameter values (compact)
	params = _get_params(operator)
	if params:
		node['pars'] = params

	# Connections: inputs (names only)
	try:
		inputs = [inp.name if inp is not None else None for inp in operator.inputs]
		while inputs and inputs[-1] is None:
			inputs.pop()
		if inputs:
			node['inputs'] = inputs
	except:
		pass

	# Connections: outputs (names only)
	try:
		outputs = [out.name for out in operator.outputs if out is not None]
		if outputs:
			node['outputs'] = outputs
	except:
		pass

	# Recurse into children (COMPs only)
	try:
		kids = operator.children
		if kids:
			children = []
			for child in sorted(kids, key=lambda c: c.name):
				child_data = serialize_op(child, depth + 1)
				if child_data:
					children.append(child_data)
			if children:
				node['children'] = children
	except:
		pass

	return node


def _add_collapsed_info(node, operator):
	"""For built-in components like Annotate, capture just the useful bits."""
	try:
		# Annotate: capture title and body text
		if operator.type == 'annotate':
			title = operator.par.Titletext.eval() if hasattr(operator.par, 'Titletext') else ''
			body = operator.par.Bodytext.eval() if hasattr(operator.par, 'Bodytext') else ''
			if title:
				node['title'] = title
			if body:
				node['body'] = body
			return

		# For other collapsed types, just capture custom params
		params = {}
		for page in operator.customPages:
			page_pars = {}
			for par in page.pars:
				val = _serialize_par(par)
				if val is not None:
					page_pars[par.name] = val
			if page_pars:
				params[page.name] = page_pars
		if params:
			node['pars'] = params
	except:
		pass


def _get_params(operator):
	"""Extract non-default parameter values as a compact dict."""
	params = {}
	try:
		# Custom pages (always include)
		for page in operator.customPages:
			page_pars = {}
			for par in page.pars:
				val = _serialize_par(par)
				if val is not None:
					page_pars[par.name] = val
			if page_pars:
				params[page.name] = page_pars

		# Built-in parameters (skip noisy pages, only non-defaults)
		for par in operator.pars():
			if par.isCustom:
				continue
			page_name = par.page.name
			if page_name in SKIP_PAGES:
				continue
			if not SKIP_DEFAULTS or not par.isDefault:
				val = _serialize_par(par)
				if val is not None:
					if page_name not in params:
						params[page_name] = {}
					params[page_name][par.name] = val
	except:
		pass
	return params


def _serialize_par(par):
	"""Serialize a single parameter to its most compact representation."""
	try:
		if par.mode == ParMode.EXPRESSION and par.expr:
			return {'expr': par.expr}
		if par.mode == ParMode.EXPORT:
			return {'export': True}
		if par.mode == ParMode.BIND:
			return {'bind': par.bindExpr}

		val = par.eval()
		if isinstance(val, float):
			if val == int(val):
				return int(val)
			return round(val, 6)
		if isinstance(val, str) and val == '':
			return None
		return val
	except:
		return None


# --- Main ---
data = {
	'project': project.name,
	'roots': [],
}

for root_path in EXPORT_ROOTS:
	root_op = op(root_path)
	if root_op is None:
		print(f"[export] Skipping {root_path} (not found)")
		continue
	root_data = serialize_op(root_op)
	if root_data:
		root_data['path'] = root_path
		data['roots'].append(root_data)

# Write compact JSON
output_path = project.folder + '/Claude Utils/network_export.json'
json_str = json.dumps(data, indent=1, default=str, ensure_ascii=False)

with open(output_path, 'w') as f:
	f.write(json_str)

size_kb = len(json_str) / 1024
print(f"[export] Exported to: {output_path}")
print(f"[export] Size: {size_kb:.0f} KB ({len(data['roots'])} roots)")
for root in data['roots']:
	def count(n):
		c = 1
		for ch in n.get('children', []):
			c += count(ch)
		return c
	print(f"[export]   {root['path']}: {count(root)} nodes")
