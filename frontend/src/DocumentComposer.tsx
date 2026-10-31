import React from 'react';
import {useAppRoute} from './appRoute';
export function DocumentComposer({children}:{children:React.ReactNode}){const route=useAppRoute();return <><div hidden={!!route.coach} inert={!!route.coach}>{children}</div>{route.coach&&<p className="small document-composer-paused" role="status">Career Coach is open. Close its panel to continue this document discussion; your unsent message is kept. Document fields and review questions remain available.</p>}</>;}
