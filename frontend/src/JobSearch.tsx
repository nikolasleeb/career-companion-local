import {listenResourceHandoff} from './resourceHandoff';
import {orderedSearches,readSelectedSearch,rememberSelectedSearch,chooseSearch,searchHistoryLabel} from './jobSearchHistory';
import {SearchSettings} from './SearchSettings';
import {CareerLevelPicker} from './CareerLevelPicker';
import {selectedSourceCount,selectedEmployerCount} from './searchSettingsState';
import {setRoute,useAppRoute,useRouteTab} from './appRoute';
import {ForYouJobs} from './ForYouJobs';
import {JobResults} from './JobResults';
import {AskJobsAI} from './AskJobsAI';
import {retireJobNotifications} from './jobNotifications';
import React,{useEffect,useMemo,useState} from 'react';
import {RolePicker} from './RolePicker';
import {LocationPicker} from './LocationPicker';
import {locationChoices} from './locationChoices';
import {locationQuery,selectedLocations} from './locationSelection';
import {preferenceSaver,recentRoles,uniqueRoles} from './jobSearchPreferences';
import './jobSearch.css';
import './jobSearchLayout.css';
type Props={accountId:string;workspace:any;call:(path:string,method?:string,body?:any)=>Promise<any>;task:(path:string,body:any,onProgress?:(value:any)=>void)=>Promise<any>;refresh:()=>Promise<void>;startApplication:(id:string)=>Promise<void>;mode:string;aiAvailable:boolean;webAvailable:boolean;busy:boolean};
const defaults={title:'',interests:[] as string[],location:'United States',workplace:'any',job_types:['internship','early_career'],days:30,employer_source_version:1,sources:['greenhouse','ashby','lever','official','adzuna','usajobs','github'],mode:'economy',refresh:false};
const browserZone=Intl.DateTimeFormat().resolvedOptions().timeZone||'America/Phoenix';
export function JobSearch({accountId,workspace,call,task,refresh,startApplication,mode,aiAvailable,webAvailable,busy}:Props){
 const initialTab=React.useRef(new URLSearchParams(location.search).has('alerts')?'alerts':!!sessionStorage.getItem('career-start-for-you:'+accountId)?'for-you':'results');
 const [query,setQuery]=useState<any>(defaults),[interests,setInterests]=useState<string[]>([]),[recent,setRecent]=useState<string[]>([]),[saveState,setSaveState]=useState('saved'),[caps,setCaps]=useState<any>({}),[tab,setTab]=useRouteTab('jobs',initialTab.current);
 const [error,setError]=useState(''),[message,setMessage]=useState(''),[pending,setPending]=useState(''),[loaded,setLoaded]=useState(false),[board,setBoard]=useState({career_url:'',company:''});

 const [locations,setLocations]=useState<string[]>([]),[locationError,setLocationError]=useState('');
 const rememberedLocation=React.useRef('');
 const [reviewSearches,setReviewSearches]=useState<Record<string,any>>({}),[matches,setMatches]=useState<Record<string,any>>({});
 const activeRoute=useAppRoute();
 const [retirementNotice,setRetirementNotice]=useState(false);
 const currentTab=React.useRef(tab);currentTab.current=tab;
 useEffect(()=>{void retireJobNotifications();},[]);
 useEffect(()=>{if(tab==='alerts'){initialTab.current='results';setRetirementNotice(true);setTab('results');}else if(tab!=='results'||activeRoute.view!=='jobs')setRetirementNotice(false);},[tab,activeRoute.view]);
 const [pageSize,setPageSize]=useState(25);

 const [roleError,setRoleError]=useState(''),[lastResults,setLastResults]=useState<Record<string,any>>({}),[employerFilter,setEmployerFilter]=useState('');
 const [suggested,setSuggested]=useState<string[]>([]),[jobTypeMode,setJobTypeMode]=useState('automatic'),[profileDefault,setProfileDefault]=useState<any>({job_types:defaults.job_types,explanation:''});

 const [settingsOpen,setSettingsOpen]=useState(false);const settingsTrigger=React.useRef<HTMLButtonElement>(null);
 function closeSettings(){setSettingsOpen(false);settingsTrigger.current?.focus();}
 useEffect(()=>{if(tab!=='results'||activeRoute.view!=='jobs')setSettingsOpen(false);},[tab,activeRoute.view]);
 const blocked=busy||!!pending;
 async function act(label:string,fn:()=>Promise<void>){if(blocked)return;setPending(label);setError('');setMessage('');try{await fn();}catch(e){setError((e as Error).message);}finally{setPending('');}}
 const saver=useMemo(()=>preferenceSaver(value=>call('/job-search/preferences','PUT',value),setSaveState),[accountId,call]);
 function preferencePayload(q=query,terms=interests,history=recent,typeMode=jobTypeMode){return {account_id:accountId,page_size:pageSize,job_type_mode:typeMode,timezone:browserZone,query:{...q,career_levels:q.job_types,title:terms[0]||'',interests:terms,mode,sources:q.sources.filter((v:string)=>v!=='web'&&v!=='jobspy')},recent_interests:history};}
 async function rememberLocation(value:string){const v=value.trim().replace(/\s+/g,' ');if(v.length<2||v.length>120||v.toLocaleLowerCase()===rememberedLocation.current)return;rememberedLocation.current=v.toLocaleLowerCase();setLocationError('');try{const r=await call('/job-search/locations','POST',{value:v,history:locations,account_id:accountId});setLocations(old=>locationChoices([v,...r.locations,...old],[],''));}catch(e){rememberedLocation.current='';setLocationError((e as Error).message);}}
 async function load(){const d=await call('/job-search/preferences?timezone='+encodeURIComponent(browserZone));setPageSize(d.preferences.data.page_size||25);setCaps(d.capabilities);setLocations(d.preferences.data.location_history||[]);setSuggested(d.suggestions||[]);setProfileDefault(d.graduation_default);const typeMode=d.preferences.data.job_type_mode;setJobTypeMode(typeMode);const q={...defaults,...d.preferences.data.query};q.sources=q.sources.filter((v:string)=>v!=='web'&&v!=='jobspy'&&!(['adzuna','usajobs'].includes(v)&&!d.capabilities[v]));let terms=uniqueRoles(q.interests?.length?q.interests:q.title?[q.title]:[],12),history=recentRoles(d.preferences.data.recent_interests||[],terms);const explorerTitle=sessionStorage.getItem('career-explorer-search:'+accountId);if(explorerTitle){sessionStorage.removeItem('career-explorer-search:'+accountId);terms=uniqueRoles([explorerTitle],12);history=recentRoles(history,terms);setTab('results');setMessage('Explore careers filled the occupation. Review the filters, then choose Search jobs. No search has started.');}setQuery(q);setInterests(terms);setRecent(history);saver.prime({...preferencePayload(q,terms,history,typeMode),timezone:d.persisted_timezone});setLoaded(true);}
 useEffect(()=>{void load().catch(e=>setError(e.message));return()=>saver.dispose();},[saver]);
 useEffect(()=>{if(activeRoute.view!=='jobs')return;let live=true,sequence=0;const update=()=>{const ticket=++sequence;void call('/job-search/preferences').then((d:any)=>{if(live&&ticket===sequence)setCaps(d.capabilities);}).catch((e:Error)=>{if(live&&ticket===sequence)setError('Could not refresh source connections: '+e.message);});};update();window.addEventListener('focus',update);return()=>{live=false;window.removeEventListener('focus',update);};},[accountId,call,activeRoute.view]);

 useEffect(()=>{const update=(e:Event)=>setQuery((q:any)=>({...q,...(e as CustomEvent).detail}));window.addEventListener('employer-sources-updated',update);return()=>window.removeEventListener('employer-sources-updated',update);},[]);
 useEffect(()=>{if(!loaded)return;if(query.location.trim().length<2||!query.sources.length||!query.job_types.length){setSaveState('invalid');return;}saver.update(preferencePayload());},[loaded,query,interests,recent,mode,jobTypeMode,pageSize,saver]);
 function rolesChanged(values:string[],added:string[]=[]){setRoleError('');setInterests(values);setRecent(v=>recentRoles(v,added));}
 useEffect(()=>listenResourceHandoff('jobs',accountId,()=>interests,values=>{rolesChanged(values,values);setTab('results');setMessage('Occupation selected. Review your filters, then choose Search jobs.');}),[accountId,interests]);
 function request(){return preferencePayload().query;}
 async function savePreferences(){saver.update(preferencePayload());await saver.flush();const latest=await call('/job-search/preferences');if(latest.preferences.data.job_type_mode==='automatic'){setProfileDefault(latest.graduation_default);setQuery((q:any)=>({...q,job_types:latest.preferences.data.query.job_types,career_levels:latest.preferences.data.query.job_types}));}return latest.preferences.data.query;}
 async function search(){const saved=await savePreferences();const result=await task('/jobs/search',{...saved,mode,refresh:query.refresh,request_token:crypto.randomUUID()});setSelectedSearch(result.id);setLastResults(v=>({...v,normal:result}));await refresh();const connections=await call('/settings/job-connections');setCaps((v:any)=>({...v,adzuna_connection:connections.adzuna}));setTab('results');}
 const available=orderedSearches(Object.values({...Object.fromEntries(workspace.search.filter((r:any)=>r.data.discovery_kind!=='for_you').map((r:any)=>[r.id,r])),...Object.fromEntries(Object.values(lastResults).map((r:any)=>[r.id,r]))}) as any[]);
 const [selectedSearch,setSelectedSearch]=useState(()=>readSelectedSearch(accountId));
 const result=chooseSearch(available,selectedSearch);
 const resultsSelector=React.useRef<HTMLSelectElement>(null);
 useEffect(()=>{if(result){setSelectedSearch(result.id);rememberSelectedSearch(accountId,result.id);}},[accountId,result?.id]);
 function previousSearches(){resultsSelector.current?.scrollIntoView({block:'center'});resultsSelector.current?.focus({preventScroll:true});}
 const match=result?matches[result.id]:null;
 useEffect(()=>{if(!result)return;let live=true;call('/job-search/ai/matches?search_id='+result.id).then((rows:any[])=>{if(live)setMatches(v=>({...v,[result.id]:rows[0]||null}));}).catch((e:Error)=>{if(live)setError(e.message);});return()=>{live=false;};},[result?.id]);
 function openReview(){if(result){setReviewSearches(v=>({...v,[result.id]:result}));setTab('compare');}}
 useEffect(()=>{if(tab==='compare'&&result&&!reviewSearches[result.id])setReviewSearches(v=>({...v,[result.id]:result}));},[tab,result?.id]);
 const valid=loaded&&interests.length>0&&query.location.trim().length>=2&&selectedSourceCount(query,caps)>0&&query.job_types.length>0;
 const searchReason=!loaded?'Loading your preferences.':blocked?'Wait for the current operation to finish.':!interests.length?'Choose at least one role to search.':query.location.trim().length<2?'Enter a location to search.':!selectedSourceCount(query,caps)?'Choose a connected source in Search settings.':!query.job_types.length?'Choose at least one career level.':'';
 const chosenLocations=selectedLocations(query);
 const externalQuery=(request().interests.length?request().interests:[query.title]).join(' OR ');
 return <><header className="job-search-heading"><span className="eyebrow">FIND YOUR NEXT OPPORTUNITY</span><h1>Job Search</h1><p>Search employer postings, keep a shortlist, and choose what to apply for. Resume generation is optional.</p></header>
 <div className="job-search-tabs" role="group" aria-label="Job search sections">{[['results','Search'],['for-you','For you · AI'],['saved','Saved jobs']].map(([id,label])=><button className={(id==='results'?['results','ai','compare'].includes(tab):tab===id)?'selected':''} aria-pressed={id==='results'?['results','ai','compare'].includes(tab):tab===id} key={id} onClick={()=>setTab(id)}>{label}</button>)}</div>
 <div hidden={tab!=='results'}><section className="panel job-search-form" aria-label="Search preferences">
 <div className="search-form-toolbar"><p className="small muted">Search your selected sources using these filters. No AI request.</p><div className="search-settings-launch"><span className="small muted">{selectedSourceCount(query,caps)} sources · {selectedEmployerCount(query,caps.employers)} employers</span><button type="button" className="button secondary" ref={settingsTrigger} aria-haspopup="dialog" disabled={!loaded} onClick={()=>setSettingsOpen(true)}>⚙ Search settings</button></div></div>
 <div className="search-primary-fields"><RolePicker selected={interests} recent={recent} suggested={suggested} groups={caps.preset_groups||{}} catalog={caps.role_catalog||[]} onChange={rolesChanged} disabled={blocked||!loaded}/><LocationPicker groups={caps.location_groups||{}} selected={chosenLocations} history={locations} catalog={caps.location_options||['United States','East Coast','West Coast']} disabled={blocked||!loaded} onChange={values=>setQuery((q:any)=>({...q,...locationQuery(values)}))} onCommit={value=>void rememberLocation(value)}/></div>
 <div className="search-compact-filters"><CareerLevelPicker values={query.job_types} automatic={jobTypeMode==='automatic'} explanation={profileDefault.explanation} disabled={blocked||!loaded} onChange={values=>{setJobTypeMode('manual');setQuery({...query,job_types:values});}} onDefault={()=>{setJobTypeMode('automatic');setQuery({...query,job_types:profileDefault.job_types});}}/><label>Posting date<select disabled={blocked||!loaded} value={query.days} onChange={e=>setQuery({...query,days:Number(e.target.value)})}>{[7,14,30,60,90].map(d=><option value={d} key={d}>Past {d} days</option>)}</select></label><label>Work arrangement<select disabled={blocked||!loaded} value={query.workplace} onChange={e=>setQuery({...query,workplace:e.target.value})}><option value="any">Any / unspecified</option><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="onsite">On-site</option></select></label></div>
 {locationError&&<p className="field-error" role="alert">Could not remember this location: {locationError} <button type="button" className="text-button" onClick={()=>void rememberLocation(query.location)}>Retry</button></p>}
 {Object.entries(caps.location_regions||{}).filter(([name])=>chosenLocations.some(v=>name.toLowerCase()===v.toLowerCase())).map(([name,states])=><details className="location-region" key={name}><summary>{name}: included states</summary><p>{(states as string[]).join(', ')}. Choose a city or state instead for a narrower search.</p></details>)}
 <div className="job-search-submit"><button className="button primary" aria-describedby={searchReason?'search-unavailable':undefined} disabled={blocked||!valid} onClick={()=>void act('Searching selected sources',()=>search())}>Search jobs</button><button type="button" className="button secondary" onClick={()=>setTab('ai')}>Describe a search · AI</button><button type="button" className="button secondary" disabled={!available.length} aria-describedby="previous-searches-help" onClick={previousSearches}>Previous searches</button></div><div className="job-search-save-status"><span className="small muted" role={saveState==='error'?'alert':'status'}>{!loaded?'Loading your preferences…':saveState==='error'?'Could not save your choices.':saveState==='invalid'?'Enter a location and choose a source to save.':saveState==='saved'?'Preferences saved automatically':'Saving preferences…'}</span>{saveState==='error'&&<button type="button" className="text-button" onClick={()=>void act('Retrying preference save',savePreferences)}>Retry save</button>}</div>
 <span id="previous-searches-help" className="sr-only">Reopen completed searches without provider or AI requests. Your searches appear here after they finish.</span>
 {searchReason&&<p className="small muted search-action-message" id="search-unavailable">{searchReason}</p>}
 <div className="job-external-links"><a className="button quiet" target="_blank" rel="noreferrer" href={'https://www.linkedin.com/jobs/search/?keywords='+encodeURIComponent(externalQuery)+'&location='+encodeURIComponent(query.location)}>Search LinkedIn ↗</a><a className="button quiet" target="_blank" rel="noreferrer" href="https://app.joinhandshake.com/stu/postings">Search Handshake ↗</a><a className="button quiet" target="_blank" rel="noreferrer" href="https://github.com/SimplifyJobs/Summer2027-Internships">Simplify internships ↗</a><a className="button quiet" target="_blank" rel="noreferrer" href="https://github.com/SimplifyJobs/New-Grad-Positions">Simplify new-grad roles ↗</a><small>These websites open separately from Career Companion search.</small></div>
 </section></div>
 {loaded&&<SearchSettings open={settingsOpen} onClose={closeSettings} onConnections={()=>{setSettingsOpen(false);setRoute({view:'settings',tab:'connections'});}} query={query} caps={caps} interests={interests} onCatalogChange={employers=>setCaps((v:any)=>({...v,employers}))} onChange={value=>setQuery((q:any)=>({...q,...value}))} call={call} blocked={blocked} saveState={saveState} onFlush={async()=>{saver.update(preferencePayload());await saver.flush();}}/>}
 <div hidden={tab!=='for-you'}><ForYouJobs {...{accountId,call,mode,aiAvailable,webAvailable,busy,refresh,startApplication,workspace,pageSize}} onSize={setPageSize}/></div>
 <div hidden={tab!=='ai'}><section className="job-search-view-heading"><button className="button secondary" onClick={()=>setTab('results')}>Back to filters</button></section></div>
 <div hidden={tab!=='ai'}><AskJobsAI panel="discover" {...{accountId,call,task,mode,aiAvailable,webAvailable,busy}} onFound={(r:any)=>{setMessage('Jobs found. Profile fit has not been reviewed. Use Check fit with my Profile for an optional paid review.');setSelectedSearch(r.id);setLastResults(v=>({...v,ai:r}));void refresh();if(currentTab.current==='ai')setTab('results');}} onMatch={()=>{}}/></div>
 {retirementNotice&&tab==='results'&&<p className="notice" role="status">Daily alerts have been retired. Search manually whenever you want.</p>}{error&&<p className="notice" role="alert">{error}</p>}{message&&<p className="notice" role="status">{message}</p>}{pending&&<p role="status">{pending}…</p>}
 <div hidden={!['results','ai','compare'].includes(tab)}>
 {result&&<section className="job-result-actions" aria-label="Selected search and Profile review"><label>Results from<select ref={resultsSelector} value={result.id} onChange={e=>{setSelectedSearch(e.target.value);if(tab==='compare')setTab('results');}}>{available.map(r=><option key={r.id} value={r.id}>{searchHistoryLabel(r)}</option>)}</select></label><button className="button secondary" aria-expanded={tab==='compare'} onClick={()=>tab==='compare'?setTab('results'):openReview()}>{tab==='compare'?'Close Profile fit review':'Check fit with my Profile · AI'}</button><p className="small muted">Viewing saved results. No new search or AI request.</p></section>}
 {Object.entries(reviewSearches).map(([id,search])=><div key={id} hidden={tab!=='compare'||result?.id!==id}><p className="small">Reviewing this saved result set: {search.data.ai_brief?'AI search':'Search'} · {new Date(search.created_at).toLocaleString()}</p><AskJobsAI panel="compare" {...{accountId,call,task,mode,aiAvailable,webAvailable,busy,search}} onFound={()=>{}} onMatch={(r:any)=>setMatches(v=>({...v,[id]:r}))}/></div>)}
 <JobResults {...{call,pageSize,startApplication,busy}} active={['results','ai','compare'].includes(tab)} match={match} applications={workspace.application} saved={false} search={result} onSize={setPageSize}/>
 </div>
 <div hidden={tab!=='saved'}><JobResults {...{call,pageSize,startApplication,busy}} active={tab==='saved'} applications={workspace.application} saved={true} search={null} onSize={setPageSize}/></div>
 </>;
}
