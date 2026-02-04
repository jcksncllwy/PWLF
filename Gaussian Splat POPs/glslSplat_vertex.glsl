uniform vec3 uFocal;
uniform vec3 uT;
uniform vec3 uR;
uniform float uS;
uniform float uScale;
uniform float uAlphaThreshold;

// Kinect displacement uniforms
uniform sampler2D uKinectDisplace;	// RGB: flow.x, flow.y, depth (from Combine TOP)
uniform mat4 uKinectVP;			// Kinect view-projection (world -> Kinect clip space)
uniform float uDisplaceStrength;	// overall displacement magnitude
uniform float uDepthFalloff;		// depth curve: higher = faster falloff with distance

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

	vec3 pos = TDPos();
	vec2 uv = pos.xy;
	vec3 conic = vec3(0.);
	vec2 ndc = vec2(0.);
	vec4 color = TDInstanceCustomAttrib3(index);

	mat3 m = mat3(1);
	vec3 posData = vec3(0.);
	vec4 rotData = vec4(0.);
	vec3 scale = vec3(0.);
	
	if (color.a > 0.0)
	{
		posData = TDInstanceCustomAttrib0(index).xyz;
		rotData = normalize(TDInstanceCustomAttrib2(index));
		scale = TDInstanceCustomAttrib1(index).xyz;
		m = RotScale(rotData, scale, uScale);
		mat3 sigma = transpose(m)*m;
		vec3 cov = Covariance(posData.xyz, cameraIndex, sigma);
		float det = cov.x * cov.z - cov.y * cov.y;
		conic = vec3(cov.z,-cov.y,cov.x)/det;

		vec2 wh = 2.*uFocal.xy * uFocal.z;
		vec2 quadwh_scr = 3.*sqrt(cov.xz);
    	ndc = 2.*quadwh_scr / wh * smoothstep(0.0,0.1,uScale);
   	uv = quadwh_scr * pos.xy;
	}
	
	else
	{
		posData *= 0; color *= 0;
	}
	
	vec4 worldSpacePos = TDDeform(posData.xyz);
	vec4 projectionSpace = TDWorldToProj(worldSpacePos);
	projectionSpace /= projectionSpace.w;

	// Kinect-driven displacement: project splat into Kinect's view,
	// sample the flow+depth texture, offset splat center in screen space
	vec4 kinectClip = uKinectVP * worldSpacePos;
	if (kinectClip.w > 0.0)
	{
		vec2 kinectUV = kinectClip.xy / kinectClip.w * 0.5 + 0.5;
		if (all(greaterThanEqual(kinectUV, vec2(0.0))) &&
			all(lessThanEqual(kinectUV, vec2(1.0))))
		{
			vec3 displace = texture(uKinectDisplace, kinectUV).rgb;
			vec2 flow = displace.xy;		// optical flow vectors (signed, float texture)
			float depth = displace.z;		// pedestrian depth, 0=close 1=far
			float weight = exp(-depth * uDepthFalloff);
			projectionSpace.xy += flow * uDisplaceStrength * weight;
		}
	}

	projectionSpace.xy += ndc*pos.xy;
	gl_Position = projectionSpace;

	Vert.position = projectionSpace.xyz;
	Vert.color = color;
	Vert.uv = uv;
	Vert.conic = conic;
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