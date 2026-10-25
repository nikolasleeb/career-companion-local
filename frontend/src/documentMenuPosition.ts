type Rect={left:number;right:number;top:number;bottom:number};
export function documentMenuPosition(anchor:Rect,size:{width:number;height:number},bounds:Rect){
 const gap=6,pad=8;
 const width=Math.min(size.width,bounds.right-bounds.left-pad*2);
 const height=Math.min(size.height,bounds.bottom-bounds.top-pad*2);
 const below=anchor.bottom+gap;
 const top=below+height<=bounds.bottom-pad?below:anchor.top-gap-height;
 return {left:Math.max(bounds.left+pad,Math.min(anchor.right-width,bounds.right-pad-width)),
  top:Math.max(bounds.top+pad,Math.min(top,bounds.bottom-pad-height)),maxHeight:bounds.bottom-bounds.top-pad*2};
}
