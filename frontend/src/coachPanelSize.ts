export const DEFAULT_COACH_WIDTH=480,MIN_COACH_WIDTH=360;
export function coachPanelLimits(viewport:number,sidebar:number){
 const available=Math.max(MIN_COACH_WIDTH,viewport-sidebar);
 return {maximum:Math.max(MIN_COACH_WIDTH,Math.min(800,available-480)),expanded:Math.max(MIN_COACH_WIDTH,Math.min(1100,available-24))};
}
export function clampCoachWidth(preferred:number,maximum:number){return Math.max(MIN_COACH_WIDTH,Math.min(maximum,Number.isFinite(preferred)?preferred:DEFAULT_COACH_WIDTH));}
