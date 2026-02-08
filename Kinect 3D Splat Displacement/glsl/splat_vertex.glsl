// Gaussian Splat Vertex/Fragment Shader for TouchDesigner
// Original splat viewer by Dan Tapper (@visualcodepoetry)
// Kinect displacement modifications for Portland Winter Lights Festival
//
// VARIANT: 3D persistent displacement (reads pre-computed world-space offsets from texture)

uniform vec3 uFocal;
uniform vec3 uT;
uniform vec3 uR;
uniform float uS;
uniform float uScale;
uniform float uAlphaThreshold;

// Persistent displacement uniforms
uniform sampler2D uSplatOffset;		// world-space offset per splat (from physics update GLSL TOP)
uniform vec2 uStateTexSize;		// state texture dimensions, e.g. vec2(1024.0, 1024.0)

#ifdef TD_VERTEX_SHADER
out Vertex
#else
in Vertex
#endif
{
	vec3 position;
	vec4 color;
	vec2 uv;
	vec3 conic;
} Vert;

#ifdef TD_VERTEX_SHADER

mat3 RotZYX(vec3 a) 
{ 
	vec3 c = cos(a), s = sin(a);
	return mat3(
		c.x*c.y, c.x*s.y*s.z - s.x*c.z, s.x*s.z + c.x*s.y*c.z,
		s.x*c.y, c.x*c.z + s.x*s.y*s.z, s.x*s.y*c.z - c.x*s.z,
		-s.y, s.z*c.y, c.y*c.z
	);
}

mat3 quatToMat3(vec4 q) 
{
  float qx = q.y, qy = q.z, qz = q.w, qw = q.x;
  float qxx = qx*qx, qyy = qy*qy, qzz = qz*qz, qxz = qx*qz, qxy = qx*qy, qyw = qy*qw, qzw = qz*qw, qyz = qy*qz, qxw = qx*qw;
  return mat3(
    vec3(1.0 - 2.0 * (qyy + qzz), 2.0 * (qxy - qzw), 2.0 * (qxz + qyw)),
    vec3(2.0 * (qxy + qzw), 1.0 - 2.0 * (qxx + qzz), 2.0 * (qyz - qxw)),
    vec3(2.0 * (qxz - qyw), 2.0 * (qyz + qxw), 1.0 - 2.0 * (qxx + qyy))
  );
}

mat3 RotScale(vec4 rot, vec3 scale, float globalScale)
{
  mat3 ms = mat3(
      uS*globalScale*exp(scale.x), 0, 0,
      0, uS*globalScale*exp(scale.y), 0,
      0, 0, uS*globalScale*exp(scale.z)
  );
  return ms*quatToMat3(rot)*RotZYX(radians(uR.zyx));
}

// Map a splat index to a UV coordinate in the state texture
vec2 indexToUV(int idx, vec2 texSize) {
	float x = float(idx % int(texSize.x)) + 0.5;
	float y = float(idx / int(texSize.x)) + 0.5;
	return vec2(x, y) / texSize;
}

vec3 Covariance(vec3 p, int cameraIndex, mat3 sigma)
{
	mat4 camMatrix = uTDMats[cameraIndex].cam;
	vec2 limit = 1.3 * uFocal.xy;
	vec4 camPos = camMatrix*vec4(p,1.);
	camPos.xy = clamp(camPos.xy/camPos.z, -limit, limit)*camPos.z;
	float focal = uFocal.z;
	mat3 J = mat3(
		focal/camPos.z, 0., -(focal*camPos.x)/(camPos.z*camPos.z),
		0., focal/camPos.z, -(focal*camPos.y)/(camPos.z*camPos.z),
		0, 0, 0
	);
	mat3 T = mat3(uTDMats[cameraIndex].camInverse)*J;
	mat3 cov = transpose(T)*transpose(sigma)*T;
	return vec3(cov[0][0] + .3, cov[0][1], cov[1][1] + .3);
}

void main()
{
	int instanceIndex = TDInstanceID();
	//int vertexIndex = int(gl_VertexID/4);
	//int index = instanceIndex * 1024 + vertexIndex;
	//int index = instanceIndex * 1024 + TDAttrib_CopyId();
	int index = instanceIndex;
	int cameraIndex = TDCameraIndex();

	// Get the original point index (before sorting) for offset texture lookup
	int originalIndex = int(TDInstanceCustomAttrib4(index).x);  // uniqueID attribute

	vec3 quadCorner = TDPos();		// xy: corner offset for billboard quad (-1 to 1)
	vec2 uv = quadCorner.xy;
	vec3 conic = vec3(0.);
	vec2 quadExtentNDC = vec2(0.);	// how far quad corners extend from center (in NDC)
	vec4 color = TDInstanceCustomAttrib3(index);

	mat3 m = mat3(1);
	vec3 splatPos = vec3(0.);		// splat center position (local/object space)
	vec4 splatRot = vec4(0.);		// splat rotation quaternion
	vec3 splatScale = vec3(0.);		// splat scale (log-encoded)

	if (color.a > 0.0)
	{
		splatPos = TDInstanceCustomAttrib0(index).xyz;
		splatRot = normalize(TDInstanceCustomAttrib2(index));
		splatScale = TDInstanceCustomAttrib1(index).xyz;
		m = RotScale(splatRot, splatScale, uScale);
		mat3 sigma = transpose(m)*m;
		vec3 cov = Covariance(splatPos.xyz, cameraIndex, sigma);
		float det = cov.x * cov.z - cov.y * cov.y;
		conic = vec3(cov.z,-cov.y,cov.x)/det;

		vec2 wh = 2.*uFocal.xy * uFocal.z;
		vec2 quadExtentScreen = 3.*sqrt(cov.xz);
		quadExtentNDC = 2.*quadExtentScreen / wh * smoothstep(0.0,0.1,uScale);
		uv = quadExtentScreen * quadCorner.xy;
	}

	else
	{
		splatPos *= 0; color *= 0;
	}

	vec4 worldPos = TDDeform(splatPos.xyz);

	// Apply persistent world-space offset from physics simulation
	// Use originalIndex (pre-sort) for texture lookup, not the current sorted index
	vec2 stateUV = indexToUV(originalIndex, uStateTexSize);
	vec3 offset = texture(uSplatOffset, stateUV).rgb;
	worldPos.xyz += offset * 10.0;  // scale to match scene (TODO: make this a uniform)

	vec4 clipPos = TDWorldToProj(worldPos);
	vec3 ndcPos = clipPos.xyz / clipPos.w;	// perspective divide: clip space -> NDC

	ndcPos.xy += quadExtentNDC * quadCorner.xy;	// expand quad corners from center
	gl_Position = vec4(ndcPos, 1.0);

	Vert.position = ndcPos;
	Vert.uv = uv;
	Vert.conic = conic;

	// Tint displaced splats based on offset direction
	float offsetLen = length(offset);
	if (offsetLen > 0.001) {
		vec3 offsetDir = normalize(offset) * 0.5 + 0.5;
		color.rgb = mix(color.rgb, offsetDir, 0.1);
	}
	Vert.color = color;
}
#endif

#ifdef TD_PIXEL_SHADER
out vec4 fragColor;
void main()
{
	vec4 color = Vert.color;
	if (color.a == 0) discard;

	vec2 d = Vert.uv;
	vec3 conic = Vert.conic.xyz;
	float power = -.5*(conic.x * d.x * d.x + conic.z * d.y * d.y) - conic.y*d.x*d.y;
  color.a = min(0.99, color.a * exp(power));
  if (power > 0. || color.a < max(uAlphaThreshold,1./255.)) discard;
	TDCheckDiscard();
  color.rgb *= color.a;
	TDAlphaTest(color.a);
	fragColor = TDOutputSwizzle(color);
}
#endif