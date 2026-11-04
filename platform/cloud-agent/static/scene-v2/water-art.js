/* Original contour study. Blue planes are generated, not sampled from the reference. */
(function (scope) {
  "use strict";
  function mix(a,b,t) { return a+(b-a)*t; }
  function hash(x,y) {
    var h = Math.imul(x,374761393) + Math.imul(y,668265263);
    h = Math.imul(h ^ (h >>> 13),1274126177);
    return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
  }
  function noise(x,y) {
    var ix=Math.floor(x), iy=Math.floor(y), u=x-ix, v=y-iy;
    u=u*u*(3-2*u);v=v*v*(3-2*v);
    return mix(mix(hash(ix,iy),hash(ix+1,iy),u),mix(hash(ix,iy+1),hash(ix+1,iy+1),u),v);
  }
  // Marching-squares contours: common edge IDs join adjacent cells without seams.
  var cases = [[],[3,0],[0,1],[3,1],[1,2],[3,0,1,2],[0,2],[3,2],
    [2,3],[0,2],[0,1,2,3],[1,2],[1,3],[0,1],[3,0],[]];
  function contours(field,nx,ny,threshold,raw) {
    var points={}, graph={};
    function edge(x,y,e,a,b,c,d) {
      var id,px,py,t;
      if(e===0) { id='h'+x+','+y;t=(threshold-a)/(b-a);px=x+t;py=y; }
      if(e===1) { id='v'+(x+1)+','+y;t=(threshold-b)/(c-b);px=x+1;py=y+t; }
      if(e===2) { id='h'+x+','+(y+1);t=(threshold-d)/(c-d);px=x+t;py=y+1; }
      if(e===3) { id='v'+x+','+y;t=(threshold-a)/(d-a);px=x;py=y+t; }
      if(!points[id]) points[id]=[px*1600/(nx-1),py*1000/(ny-1)];
      return id;
    }
    for(var y=0;y<ny-1;y++) for(var x=0;x<nx-1;x++) {
      var a=field[y*nx+x],b=field[y*nx+x+1],c=field[(y+1)*nx+x+1],d=field[(y+1)*nx+x];
      var mask=(a>threshold?1:0)|(b>threshold?2:0)|(c>threshold?4:0)|(d>threshold?8:0);
      var line=cases[mask];
      for(var k=0;k<line.length;k+=2) {
        var one=edge(x,y,line[k],a,b,c,d),two=edge(x,y,line[k+1],a,b,c,d);
        (graph[one]||(graph[one]=[])).push(two);(graph[two]||(graph[two]=[])).push(one);
      }
    }
    var seen={}, paths=[], polygons=[];
    Object.keys(graph).forEach(function(first) {
      if(seen[first]) return;
      var poly=[],id=first,prev=null;
      while(!seen[id]) {
        seen[id]=true;poly.push(points[id]);
        var list=graph[id],next=list[0]===prev?list[1]:list[0];
        prev=id;id=next;
        if(!id)break;
      }
      if(poly.length<5)return;
      polygons.push(poly);
      var n=poly.length, start=poly[n-1],end=poly[0];
      var out='M'+((start[0]+end[0])/2).toFixed(1)+','+((start[1]+end[1])/2).toFixed(1);
      for(var i=0;i<n;i++) {
        var p=poly[i],q=poly[(i+1)%n];
        out+='Q'+p[0].toFixed(1)+','+p[1].toFixed(1)+' '+((p[0]+q[0])/2).toFixed(1)+','+((p[1]+q[1])/2).toFixed(1);
      }
      paths.push(out+'Z');
    });
    return raw ? polygons : paths.join('');
  }
  function build(time,raw) {
    var nx=103,ny=89,field=new Float32Array(nx*ny), flecks=new Float32Array(nx*ny);
    for(var j=0;j<ny;j++) for(var i=0;i<nx;i++) {
      if(i===0||j===0||i===nx-1||j===ny-1) {field[j*nx+i]=0;continue;}
      var x=i*1600/(nx-1),y=j*1000/(ny-1),depth=y/1000;
      // Perspective grows the reflections towards the foreground. No uniform rows.
      var u=(x-500)/(90+depth*210),v=Math.log(1+y/190)*11.5;
      var drift=time*.095;
      var wu=u+.82*noise(u*.64+4,v*.53-1)+Math.sin(drift+v)*.11;
      var wv=v+.72*noise(u*.51-3,v*.62+7)+Math.cos(drift*.8+u)*.13;
      var f=.64*noise(wu+17,wv-9)+.27*noise(wu*2.1+5,wv*2.1+8)+.09*noise(wu*4.3-8,wv*4.3+2);
      field[j*nx+i]=f;
      flecks[j*nx+i]=y<440 ? .7*noise(x/43+31,y/15+11)+.3*noise(x/22-15,y/8+2) : 0;
    }
    var out=[.44,.57,.68].map(function(level) {return contours(field,nx,ny,level,raw);});
    out.push(contours(flecks,nx,ny,.67,raw));return out;
  }
  scope.VelaWaterArt={build:build,geometry:function(){return build(0,true);}};
}(typeof window !== 'undefined' ? window : globalThis));
