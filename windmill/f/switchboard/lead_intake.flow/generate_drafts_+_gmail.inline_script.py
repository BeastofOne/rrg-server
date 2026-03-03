# Module D: Generate Drafts with Gmail Draft Creation
# Uses Gmail API directly via OAuth to create drafts in teamgotcher@gmail.com
#
# Commercial templates (Crexi/LoopNet), BizBuySell templates, and Lead Magnet signed by Larry.
# Residential templates (Realtor.com, Seller Hub, Social Connect, UpNest) signed by Andrea.
# Followup detection comes from Module A (WiseAgent notes), not Gmail sent folder.

#extra_requirements:
#google-api-python-client
#google-auth

import wmill
import json
import base64
from email.mime.text import MIMEText
from datetime import datetime, timezone
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials


# ~500 common US first names (SSA data) for validating lead names vs company names
COMMON_FIRST_NAMES = {
    "aaden","aadhya","aadya","aaleyah","aaliyah","aamir","aaniyah","aanya","aaradhya","aaralyn",
    "aarav","aariv","aarna","aaron","aarush","aarya","aaryan","aayan","aayden","abagail",
    "abbey","abbi","abbie","abbigail","abbigale","abby","abbygail","abdiel","abdirahman","abdul",
    "abdulaziz","abdullah","abdullahi","abdulrahman","abe","abel","abhinav","abhiram","abigail","abigale",
    "abigayle","abner","abraham","abram","abriana","abrianna","abriella","abrielle","abril","abygail",
    "acacia","ace","achilles","ada","adah","adair","adalberto","adalee","adaleigh","adalia",
    "adalie","adalina","adalind","adaline","adalyn","adalynn","adalynne","adam","adamari","adamaris",
    "adan","addalyn","addalynn","addelyn","addie","addilyn","addilynn","addisen","addison","addisyn",
    "addysen","addyson","adela","adelaide","adele","adelia","adelina","adeline","adell","adella",
    "adelle","adelyn","adelynn","aden","adia","adiel","adilene","adilyn","adilynn","adin",
    "adina","adira","adison","adisyn","aditi","aditya","adlee","adleigh","adler","adley",
    "adnan","adolfo","adolph","adonis","adrain","adreanna","adria","adrian","adriana","adriane",
    "adrianna","adrianne","adriano","adriel","adrien","adriene","adrienne","advik","adyn","adysen",
    "adyson","aedan","aeden","aerial","afton","agastya","agatha","agnes","agustin","ahmad",
    "ahmed","ahmir","ahsley","ahtziri","aida","aidan","aide","aiden","aidyn","aila",
    "ailani","ailany","aileen","ailyn","aime","aimee","ainhoa","ainsley","aisha","aislinn",
    "aislyn","aislynn","aitana","aiyana","aiyanna","aiza","aizen","aja","ajani","ajay",
    "ajee","akash","akasha","akayla","akeelah","akeem","akilah","akira","akiva","aksel",
    "akshara","al","alahni","alaia","alaiah","alaina","alaiya","alaiyah","alan","alana",
    "alanah","alani","alanis","alanna","alannah","alara","alaric","alasia","alaska","alaya",
    "alayah","alayla","alayna","alaysha","alaysia","alba","albert","alberta","albertha","alberto",
    "albin","albina","alda","aldair","alden","aldo","alea","aleah","alec","alecia",
    "aleeah","aleena","aleeyah","aleia","aleigha","aleisha","alejandra","alejandro","alek","aleksander",
    "aleksandra","alena","alene","alesha","aleshia","alesia","alessa","alessandra","alessandro","alessia",
    "alessio","aleta","aletha","alethea","alex","alexa","alexande","alexander","alexandr","alexandra",
    "alexandre","alexandrea","alexandria","alexandro","alexavier","alexcia","alexi","alexia","alexis","alexius",
    "alexsandra","alexus","alexys","alexzander","aleyah","aleyda","aleyna","alfonso","alford","alfred",
    "alfreda","alfredo","ali","alia","aliah","aliana","alianna","alice","alicia","alijah",
    "alina","aline","alisa","alisha","alishia","alisia","alison","alissa","alisson","alistair",
    "alister","alita","alivia","alix","aliya","aliyah","aliyana","aliza","alize","allan",
    "allegra","allen","allene","alli","allie","allison","allissa","allisson","alliyah","ally",
    "allysa","allyson","allyssa","alma","almeda","alois","aloma","alona","alondra","alonna",
    "alonso","alonzo","alora","aloysius","alpha","alphonse","alphonso","alta","althea","alton",
    "alva","alvaro","alvera","alverta","alvie","alvin","alvina","alvis","alya","alyana",
    "alyanna","alyce","alycia","alyna","alysa","alyse","alysha","alyshia","alysia","alyson",
    "alyssa","alyssia","alysson","alyvia","amaia","amaira","amairani","amaiya","amal","amalia",
    "aman","amanda","amani","amar","amara","amarah","amare","amari","amaria","amariah",
    "amarie","amarion","amaris","amauri","amaya","amayah","amber","amberly","ambria","ambrose",
    "ameer","ameera","ameerah","amelia","amelie","america","americo","amerie","amethyst","ami",
    "amia","amiah","amias","amie","amila","amilia","amina","aminah","amir","amira",
    "amiracle","amirah","amiri","amit","amity","amiya","amiyah","ammar","ammon","amor",
    "amora","amos","amoura","amy","amya","amyah","amyra","ana","anabel","anabella",
    "anabelle","anahi","anai","anaiah","anais","anaisha","anaiya","anaiyah","anakin","analeah",
    "analee","analeigh","anali","analia","analicia","analiese","analisa","analise","analy","ananda",
    "ananya","anas","anastacia","anastasia","anay","anaya","anayah","anayeli","ander","anders",
    "anderson","andi","andie","andon","andra","andrae","andre","andrea","andreas","andrei",
    "andreina","andres","andrew","andria","andy","aneesa","anessa","anette","anfernee","angel",
    "angela","angelena","angeles","angelia","angelic","angelica","angelie","angelika","angelina","angeline",
    "angelique","angelita","angella","angelo","angely","angie","angus","ani","ania","aniah",
    "anijah","anika","anisa","anish","anisha","anissa","aniston","anistyn","anita","anitra",
    "aniya","aniyah","anja","anjali","anjanette","anjelica","ann","anna","annabel","annabell",
    "annabella","annabelle","annabeth","annalee","annaleigh","annaliese","annalisa","annalise","annalynn","annamae",
    "annamarie","anne","anneliese","annelise","annemarie","annetta","annette","annie","annika","anniston",
    "annistyn","annmarie","ansel","ansh","ansleigh","ansley","anson","anthony","antione","antionette",
    "antoine","antoinette","anton","antone","antonella","antonette","antoni","antonia","antonio","antony",
    "antwain","antwan","antwon","antwone","anushka","anwar","anya","anyah","anyla","anylah",
    "anyssa","aoife","apollo","april","apryl","arabella","arabelle","araceli","aracely","aram",
    "arantza","aranza","arath","araya","arayah","archer","archie","ardella","arden","ardeth",
    "ardis","ardith","areli","arely","ares","aretha","arham","ari","aria","ariadna",
    "ariadne","ariah","arian","ariana","ariane","arianna","arianne","arianny","aribella","aric",
    "arie","ariel","ariela","ariella","arielle","aries","arihanna","arika","arionna","arissa",
    "ariya","ariyah","ariyana","ariyanna","arizona","arjun","arleen","arlen","arlene","arlet",
    "arleth","arlette","arlie","arline","arlo","arly","armaan","arman","armand","armando",
    "armani","armon","armoni","arnav","arnold","arnulfo","aron","arriana","arron","arrow",
    "arsenio","art","artemis","arther","arthur","artie","artis","arturo","arvid","arvin",
    "arwen","arya","aryah","aryan","aryana","aryanna","aryeh","aryn","asa","asahd",
    "asaiah","ash","asha","ashante","ashanti","ashely","asher","ashia","ashlea","ashlee",
    "ashlei","ashleigh","ashley","ashli","ashlie","ashlin","ashly","ashlyn","ashlynn","ashtin",
    "ashton","ashtyn","asia","asiah","asiya","asma","aspen","aspyn","aston","astrid",
    "asya","atarah","athan","atharv","athena","atiya","atlas","atreus","atreyu","atticus",
    "aubree","aubreigh","aubrey","aubri","aubriana","aubrianna","aubrie","aubriella","aubrielle","aubry",
    "auden","audie","audra","audree","audrey","audriana","audrianna","audrie","audrina","august",
    "augusta","augustine","augustus","aundrea","aura","aurelia","aurelio","aurora","austen","austin",
    "auston","austyn","autum","autumn","ava","avah","avalee","avalon","avalyn","avalynn",
    "avani","avarie","avary","avaya","avayah","aveline","aven","averi","averie","avery",
    "avi","avia","avian","aviana","avianna","avigail","avion","avis","aviva","avraham",
    "avril","avrohom","avyaan","avyan","avyanna","axel","axl","axle","axton","aya",
    "ayaan","ayah","ayan","ayana","ayanna","ayansh","ayat","aydan","ayden","aydenn",
    "aydin","ayesha","ayla","aylah","aylani","ayleen","aylin","ayman","aymar","ayra",
    "aysha","aysia","ayush","ayva","ayvah","ayven","azael","azai","azalea","azaria",
    "azariah","azeneth","aziel","azrael","azriel","azucena","azul","azure","babette","baby",
    "babyboy","babygirl","baila","bailee","baileigh","bailey","bailie","baker","bambi","bane",
    "banks","barb","barbara","barbie","barbra","barney","baron","barrett","barrie","barron",
    "barry","bart","barton","basil","bastian","batsheva","baylee","bayleigh","bayley","baylie",
    "baylor","bayron","bear","beatrice","beatrix","beatriz","beau","beaux","becca","beck",
    "beckett","beckham","becki","beckie","becky","belen","belinda","bella","bellamy","bellarose",
    "belle","belva","ben","benaiah","benedict","benicio","benita","benito","benjamin","benji",
    "bennett","bennie","benny","benson","bentlee","bentley","bently","benton","berenice","berkeley",
    "berklee","berkley","bernadette","bernadine","bernard","bernardo","berneice","bernice","bernie","berniece",
    "bernita","berry","bert","berta","bertha","bertie","bertram","beryl","bess","bessie",
    "beth","bethanie","bethann","bethany","bethel","bethzy","betsy","bette","bettie","bettina",
    "betty","bettye","betzaida","betzy","beulah","bev","beverley","beverly","bexley","beyonce",
    "bianca","bianka","bilal","bill","billie","billiejo","billy","billye","birdie","bishop",
    "bjorn","blade","blaine","blair","blaire","blaise","blake","blakelee","blakely","blakelyn",
    "blanca","blanch","blanche","blane","blayke","blayne","blaze","blessing","blessyn","blossom",
    "blythe","bo","boaz","bob","bobbi","bobbie","bobby","bobbye","bode","boden",
    "bodhi","bodie","bonita","bonnie","bonny","booker","boone","boston","bowen","bowie",
    "boyce","boyd","brad","braden","bradford","bradlee","bradley","bradly","bradon","brady",
    "bradyn","braeden","braedon","braedyn","braelyn","braelynn","braiden","brain","brandan","brande",
    "brandee","branden","brandi","brandie","brandin","brandis","brando","brandon","brandt","brandy",
    "brandyn","brannon","branson","brant","brantlee","brantley","brantly","braulio","braven","braxten",
    "braxton","braxtyn","brayan","brayden","braydin","braydon","braylan","braylee","brayleigh","braylen",
    "braylin","braylon","braylynn","brayson","brayton","brea","breana","breann","breanna","breanne",
    "brecken","bree","breeana","breeanna","brenda","brendan","brenden","brendon","brenna","brennan",
    "brennen","brennon","brent","brentley","brently","brenton","breon","breona","breonna","bret",
    "brett","brevin","brexton","bria","brian","briana","brianda","brianna","brianne","briar",
    "brice","bridger","bridget","bridgett","bridgette","brie","brieanna","briella","brielle","brien",
    "brienne","brigette","briggs","brigham","brighton","brigid","brigitte","brihanna","brilee","briley",
    "brinlee","brinley","briona","brionna","brisa","briseida","briseis","briseyda","brissa","brissia",
    "bristol","britani","britany","britnee","britney","britni","britny","britt","britta","brittaney",
    "brittani","brittanie","brittany","britteny","brittnay","brittnee","brittney","brittni","brittnie","brittny",
    "britton","brixton","briza","broc","brock","broden","broderick","brodey","brodie","brody",
    "brogan","bronson","bronte","bronx","brook","brooke","brookelyn","brookelynn","brooklin","brooklyn",
    "brooklynn","brooklynne","brooks","bruce","bruno","bryan","bryana","bryanna","bryant","bryce",
    "brycen","bryden","bryer","brylee","bryleigh","brylie","bryn","brynlee","brynleigh","brynley",
    "brynn","brynna","brynne","brynnlee","bryon","brysen","bryson","brystol","bryton","buck",
    "bud","buddy","buffy","buford","bulah","burl","burt","burton","buster","butch",
    "byron","cadance","cade","caden","cadence","cady","caeden","cael","caelan","caelyn",
    "caiden","cailey","cailin","cailyn","cain","cairo","caitlin","caitlyn","caitlynn","caius",
    "cal","calandra","calder","cale","caleb","caleigh","calen","caley","cali","calista",
    "caliyah","calla","callahan","callan","calleigh","callen","calli","callie","calliope","callista",
    "callum","cally","calum","calvin","cam","cambree","cambria","cambrie","camden","camdyn",
    "camellia","cameran","cameron","cameryn","cami","camila","camilla","camille","camilo","camisha",
    "cammie","campbell","camren","camron","camryn","canaan","candace","candi","candice","candida",
    "candie","candis","candy","candyce","cannon","canon","canyon","capri","caprice","cara",
    "caren","carey","cari","carie","carin","carina","carisa","carissa","carl","carla",
    "carlee","carleen","carleigh","carlene","carleton","carley","carli","carlie","carlo","carlos",
    "carlotta","carlton","carly","carlyle","carmel","carmela","carmelita","carmella","carmello","carmelo",
    "carmen","carmine","carol","carolann","carole","carolee","carolina","caroline","carolyn","carolyne",
    "carolynn","caron","carri","carrie","carrington","carrol","carroll","carsen","carson","carsten",
    "carsyn","carter","cartier","carver","cary","caryl","caryn","carys","casandra","case",
    "casen","casey","cash","cashton","casie","casimer","casimir","cason","casper","caspian",
    "cassandr","cassandra","cassaundra","cassi","cassian","cassidy","cassie","cassius","cassondra","cassy",
    "castiel","cataleya","catalina","cate","catelyn","catera","catharine","catherin","catherine","cathey",
    "cathi","cathie","cathleen","cathrine","cathryn","cathy","catina","catrina","cattleya","cayde",
    "cayden","caydence","cayla","caylee","cayleigh","caylie","caylin","caysen","cayson","ceara",
    "cecelia","cecil","cecile","cecilia","cecily","cedar","cedric","cedrick","celena","celene",
    "celeste","celestine","celia","celina","celine","cesar","chace","chad","chadd","chadrick",
    "chadwick","chaim","chaka","chana","chance","chancellor","chanda","chandler","chandra","chanel",
    "chanell","chanelle","channing","chantal","chante","chantel","chantell","chantelle","charde","charis",
    "charisma","charissa","charisse","charity","charla","charlee","charleen","charleigh","charlene","charles",
    "charleston","charley","charli","charlie","charline","charlize","charlotte","charly","charm","charmaine",
    "chase","chasity","chassidy","chastelyn","chastity","chauncey","chava","chaya","chayce","chayse",
    "chayton","chaz","chelcie","chelsea","chelsee","chelsey","chelsi","chelsie","chelsy","cher",
    "cherelle","cheri","cherie","cherilyn","cherise","cherish","cherokee","cherrelle","cherri","cherrie",
    "cherry","cherryl","cheryl","cheryle","cheryll","chesney","chester","chet","chevelle","chevy",
    "cheyann","cheyanna","cheyanne","cheyenne","chiara","chimere","china","chip","chiquita","chloe",
    "chloee","chloie","chosen","chris","chrissy","christa","christal","christel","christen","christene",
    "christi","christian","christiana","christianna","christie","christin","christina","christine","christion","christofer",
    "christop","christoper","christophe","christopher","christy","chrystal","chuck","chyanne","chyenne","chyna",
    "chynna","cian","ciana","cianna","ciara","ciarra","cicely","cielo","cienna","ciera",
    "cierra","ciji","cillian","cinda","cindi","cindy","cinnamon","cinthia","citlali","citlalli",
    "citlally","citlaly","clair","claira","claire","clara","clarance","clare","clarence","claribel",
    "clarice","clarisa","clarissa","clark","clarke","claud","claude","claudette","claudia","claudie",
    "claudine","claudio","clay","clayton","clem","clement","clementine","cleo","cleta","cletus",
    "cleveland","cliff","clifford","clifton","clint","clinton","cloe","cloey","clover","clyde",
    "coby","coco","codey","codi","codie","cody","coen","cohen","colbie","colby",
    "cole","coleen","coleman","coleson","coleton","colette","colin","colleen","collette","collin",
    "collins","colson","colt","colten","colter","coltin","colton","coltyn","columbus","concepcion",
    "concetta","conner","connie","connor","conor","conrad","constance","constantine","consuela","consuelo",
    "contessa","contina","cooper","cora","coraima","coral","coralie","coraline","corban","corbin",
    "corbyn","cordaro","corde","cordelia","cordell","cordero","corene","coretta","corey","cori",
    "corie","corina","corine","corinna","corinne","corissa","corliss","cormac","cornelia","cornelius",
    "cornell","corrie","corrina","corrine","corry","cortez","cortney","cory","cosette","cotina",
    "coty","courteney","courtland","courtnee","courtney","courtnie","coy","craig","creed","crew",
    "cris","crissy","crista","cristal","cristen","cristi","cristian","cristiano","cristie","cristin",
    "cristina","cristine","cristobal","cristofer","cristopher","cristy","crosby","cru","crue","cruz",
    "crysta","crystal","crystle","cullen","curt","curtis","curtiss","cy","cydney","cyle",
    "cyndi","cynthia","cyril","cyrus","dacia","daenerys","dafne","dahlia","daija","daijah",
    "dailyn","daira","daisha","daisy","daja","dajah","dajour","dajuan","dakari","dakoda",
    "dakota","dakotah","dalary","dale","daleysa","daleyza","dalia","dalila","dalilah","dallas",
    "dallin","dalton","dalvin","damani","damarcus","damari","damarion","damaris","dameon","damian",
    "damien","damion","damir","damita","damon","damond","damoni","damya","dan","dana",
    "danae","dandre","dane","daneen","danelle","danesha","danette","dangelo","dani","dania",
    "danial","danica","daniel","daniela","daniele","daniell","daniella","danielle","danika","danilo",
    "danisha","danita","daniya","daniyah","danna","dannette","dannie","dannielle","danny","dante",
    "danya","danyel","danyell","danyelle","daphne","daquan","dara","darby","darci","darcie",
    "darcy","daren","darey","daria","darian","dariana","dariel","darien","darin","dario",
    "darion","darius","darla","darleen","darlene","darline","darnell","daron","darrel","darrell",
    "darren","darrian","darrick","darrien","darrin","darrion","darrius","darron","darryl","darwin",
    "daryl","daryle","daryn","dasani","dash","dasha","dashaun","dashawn","dashiell","dasia",
    "daulton","daunte","davante","dave","daven","daveon","davi","davian","david","davida",
    "davien","davin","davina","davion","davis","davon","davonta","davonte","davy","dawn",
    "dawna","dawne","dawson","dawsyn","dax","daxon","daxton","dayami","dayana","dayanara",
    "dayanna","daylan","dayle","daylen","daylin","daylon","dayna","dayne","dayra","daysha",
    "dayton","deacon","dean","deana","deandra","deandre","deandrea","deangelo","deann","deanna",
    "deanne","deante","deanthony","deasia","deb","debbi","debbie","debbra","debby","debi",
    "debora","deborah","debra","debrah","debroah","decker","declan","dede","dedra","dedric",
    "dedrick","dee","deeann","deedee","deegan","deena","deidra","deidre","deion","deirdre",
    "deisy","deja","dejah","dejon","dejuan","deklan","del","delaney","delanie","delano",
    "delbert","delia","delicia","delila","delilah","delinda","delisa","della","delma","delmar",
    "delmer","delois","delores","deloris","delphia","delphine","delta","delvin","demarco","demarcus",
    "demari","demario","demarion","demarius","demetra","demetri","demetria","demetrius","demi","demond",
    "demonte","dempsey","dena","deneen","denice","denim","denine","denis","denise","denisha",
    "denisse","denita","denna","dennis","denny","denver","denzel","denzell","deon","deondre",
    "deonna","deonta","deontae","deonte","dequan","dereck","derek","dereon","deric","derick",
    "derik","derion","deron","derrek","derrell","derrick","derrik","derwin","desean","deshaun",
    "deshawn","desirae","desire","desiree","desmond","dessie","destanie","destany","desteny","destin",
    "destine","destinee","destiney","destini","destinie","destiny","destry","detra","dev","devan",
    "devansh","devante","devaughn","deven","devin","devion","devlin","devon","devonta","devontae",
    "devonte","devorah","devyn","dewayne","dewey","dewitt","dexter","deyanira","dezmond","dhruv",
    "diamond","dian","diana","diandra","diane","diann","dianna","dianne","dick","dickie",
    "diego","diesel","dijon","dilan","dillan","dillion","dillon","dimitri","dina","dinah",
    "dino","dion","dione","dionna","dionne","dionte","dior","diquan","dirk","divine",
    "divya","dixie","diya","djuana","djuna","dock","dollie","dolly","dolores","doloris",
    "domenic","domenica","domenick","dominga","domingo","dominic","dominick","dominik","dominique","dominque",
    "domonique","don","dona","donald","donavan","donavin","donavon","dondre","donita","donn",
    "donna","donnell","donnie","donny","donovan","donta","dontae","donte","dontrell","donya",
    "dora","dorcas","doreen","dorene","doretha","doretta","dori","dorian","dorien","dorinda",
    "doris","dorla","dorotha","dorothea","dorothy","dorris","dorsey","dortha","dorthy","dottie",
    "doug","douglas","douglass","dov","dovid","dovie","doyle","draco","drake","draven",
    "draya","drayden","dream","drema","drew","duane","dudley","duke","dulce","duncan",
    "durell","durrell","durward","dustin","dusty","dustyn","dwain","dwaine","dwan","dwane",
    "dwayne","dwight","dyan","dylan","dyland","dyllan","dyllon","dylon","dymond","dynasty",
    "eamon","ean","earl","earle","earlene","earline","earnest","earnestine","eartha","eason",
    "easter","easton","eben","eboni","ebonie","ebony","echo","ed","eda","edd",
    "eddie","eddy","eden","eder","edgar","edgardo","edie","edison","edith","edmond",
    "edmund","edna","edric","edrick","edsel","edson","eduardo","edward","edwardo","edwin",
    "edwina","edythe","effie","efrain","efren","egypt","ehlani","eian","eiden","eila",
    "eileen","eisley","eitan","eithan","eiza","ela","elaina","elaine","elam","elan",
    "elana","elani","elara","elayna","elayne","elbert","elda","elden","eldon","eldora",
    "eldred","eldridge","eleanor","eleanora","eleanore","eleazar","elena","eleni","elenora","elexis",
    "elexus","eli","elia","eliam","elian","eliana","elianna","elias","elicia","elida",
    "eliel","eliezer","elijah","elin","elina","elinor","elio","eliora","eliot","elisa",
    "elisabeth","elise","eliseo","elisha","elissa","eliyahu","eliyanah","eliza","elizabet","elizabeth",
    "ella","elle","ellen","ellery","elli","ellia","elliana","ellianna","ellie","elliette",
    "elliot","elliott","ellis","ellison","ellsworth","elly","ellyana","ellyn","elma","elmer",
    "elmira","elmo","elmore","elna","elnora","elodie","eloisa","eloise","elon","elora",
    "elouise","elowen","elowyn","eloy","elroy","elsa","elsie","elsy","elton","elva",
    "elvera","elvia","elvin","elvira","elvis","elwin","elwood","elwyn","ely","elyana",
    "elyas","elyjah","elyse","elysia","elyssa","elzie","ema","emalee","emalyn","emani",
    "emanuel","ember","emberlee","emberleigh","emberly","emberlyn","emberlynn","emelia","emeline","emely",
    "emelyn","emerald","emeri","emerie","emerson","emersyn","emery","emi","emil","emile",
    "emilee","emili","emilia","emiliana","emiliano","emilie","emilio","emily","emir","emma",
    "emmalee","emmaleigh","emmaline","emmalyn","emmalynn","emmanuel","emmarie","emme","emmeline","emmerson",
    "emmet","emmett","emmi","emmie","emmit","emmitt","emmy","emogene","emoni","emori",
    "emory","empress","emrie","emry","emrys","ender","enid","enoch","enrique","ensley",
    "enzo","eowyn","ephraim","era","eric","erica","erich","erick","ericka","erik",
    "erika","erin","erinn","eris","erlinda","erma","ermias","erna","ernest","ernestina",
    "ernestine","ernesto","ernie","eros","errol","ervin","erwin","erykah","eryn","esai",
    "esha","esmae","esme","esmeralda","esperanza","essence","essie","esta","esteban","estefani",
    "estefania","estefany","estela","estell","estella","estelle","ester","estevan","esther","estrella",
    "eternity","ethan","ethel","ethelyn","ethen","ethyn","etta","eugene","eugenia","eula",
    "eulalia","eunice","eva","evalina","evalyn","evalynn","evan","evander","evangelina","evangeline",
    "eve","evelin","evelina","evelyn","evelyne","evelynn","ever","everardo","everest","everett",
    "everette","everlee","everleigh","everley","everly","evette","evie","evin","evita","evolet",
    "evon","evonne","ewan","ezekiel","ezequiel","ezra","ezrah","fabian","fabiola","faigy",
    "faith","fallon","falon","fannie","fanny","fantasia","farah","faris","faron","farrah",
    "fatima","fatimah","fatoumata","favian","fawn","fay","faye","fayth","federico","felecia",
    "felicia","felicity","felipe","felisha","felix","felton","female","ferdinand","fern","fernanda",
    "fernando","ferne","fidel","filip","filomena","finleigh","finley","finn","finnegan","finnian",
    "finnick","finnigan","finnley","fiona","fischer","fisher","fitzgerald","fletcher","flint","flor",
    "flora","florence","florene","florian","florine","flossie","floy","floyd","flynn","fonda",
    "fontella","ford","forest","forrest","foster","fox","fran","frances","francesca","francesco",
    "franchesca","francine","francis","francisca","francisco","franco","frank","frankie","franklin","franklyn",
    "fred","freda","freddie","freddy","frederic","frederick","fredric","fredrick","fredy","freeman",
    "freida","freya","freyja","frida","frieda","fritz","fynn","gabe","gabriel","gabriela",
    "gabriell","gabriella","gabrielle","gadiel","gael","gage","gaia","gaige","gail","gale",
    "galen","galilea","gannon","gareth","garett","garfield","garland","garnet","garret","garrett",
    "garrick","garrison","garry","garth","gary","gatlin","gauge","gaven","gavin","gavyn",
    "gay","gaye","gayla","gayle","gaylene","gaylord","gaynell","gearld","gearldine","geary",
    "geena","gema","gemma","gena","genaro","gene","genea","general","genese","genesis",
    "geneva","genevieve","genna","gentry","geoffrey","george","georgene","georgette","georgia","georgiana",
    "georgianna","georgie","georgina","geovanni","geovanny","geovany","gerald","geraldine","geraldo","geralyn",
    "gerard","gerardo","geri","germaine","german","gerri","gerry","gerson","gertie","gertrude",
    "gia","giada","gian","giana","giancarlo","gianluca","gianna","gianni","giannis","giavanna",
    "gibson","gideon","gidget","gigi","gil","gilbert","gilberto","gilda","gillian","gina",
    "ginger","ginny","gino","gionni","giovani","giovanna","giovanni","giovanny","giovany","gisel",
    "gisela","gisele","gisell","giselle","gissel","gissell","gisselle","gitty","giulia","giuliana",
    "giulianna","giulietta","giuseppe","gizelle","gladys","glen","glenda","glendon","glendora","glenn",
    "glenna","glinda","gloria","glory","glynda","glynis","glynn","golda","goldie","gonzalo",
    "gordon","grace","gracee","gracelyn","gracelynn","gracen","gracey","graci","gracie","graciela",
    "gracyn","grady","graeme","graham","granger","grant","granville","gray","grayce","grayden",
    "graydon","graysen","grayson","grecia","greg","gregg","greggory","gregorio","gregory","greidys",
    "greta","gretchen","gretta","grey","greydis","greysen","greyson","griffen","griffin","grisel",
    "griselda","grover","guadalupe","guido","guillermo","guinevere","gunnar","gunner","gus","gussie",
    "gustave","gustavo","guy","gwen","gwenda","gwendolyn","gwenyth","gwyn","gwyneth","hadassah",
    "haddie","haden","hadi","hadlee","hadleigh","hadley","hafsa","hagen","haiden","haidyn",
    "hailee","haileigh","hailey","hailie","haily","haisley","haizley","hakeem","hal","halee",
    "haleigh","haley","hali","halie","halle","halley","hallie","halo","hamza","hana",
    "hanah","hank","hanna","hannah","hans","hansel","harding","hardy","harlan","harland",
    "harlee","harleen","harleigh","harlem","harley","harlie","harlow","harlyn","harlynn","harmon",
    "harmoni","harmonie","harmony","harold","harper","harriet","harriett","harriette","harris","harrison",
    "harry","hartley","harvey","hasan","haskell","hassan","hattie","havana","haven","hawa",
    "hayden","haydn","hayes","haylee","hayleigh","hayley","hayli","haylie","haywood","hazel",
    "heath","heather","heaven","heavenly","hector","hedwig","hedy","heidi","heidy","helen",
    "helena","helene","hellen","hendrix","henley","henri","henrietta","henrik","henry","hensley",
    "herbert","heriberto","herlinda","herman","hermon","hernan","herschel","hershel","hester","hettie",
    "hezekiah","hilary","hilda","hildegarde","hillary","hilma","hilton","hiram","hobart","hobert",
    "holden","holland","holley","holli","hollie","hollis","holly","hollyn","homer","honesty",
    "honey","honor","hoover","hope","horace","horacio","hortense","houston","howard","hoyt",
    "hubert","huck","hudson","huey","hugh","hugo","hulda","humberto","hunter","huntleigh",
    "hussain","hussein","huxley","huxton","hyman","hyrum","iain","ian","ibrahim","ida",
    "idalis","idell","idella","idris","ieisha","iesha","ieshia","ignacio","ike","iker",
    "ila","ilan","ilana","ileana","ilene","iliana","ilona","ilse","ilyas","ima",
    "iman","imani","imanol","imari","imelda","immanuel","imogen","imogene","imran","ina",
    "inaaya","inara","inaya","india","indiana","indie","indigo","indy","indya","ines",
    "inez","infant","inga","inger","ingrid","iola","iona","ione","ira","ireland",
    "irelyn","irelynn","irene","iridian","irie","irina","iris","irma","irvin","irving",
    "irwin","isa","isaac","isaak","isabel","isabela","isabell","isabella","isabelle","isac",
    "isadora","isadore","isael","isai","isaiah","isaias","isamar","isela","isha","ishaan",
    "ishan","ishmael","isiah","isidore","isidro","isis","isla","ismael","ismail","isobel",
    "israel","isreal","issabella","issac","isyss","italia","italy","itzae","itzayana","itzel",
    "iva","ivaan","ivan","ivana","ivanka","ivanna","ivette","ivey","ivonne","ivory",
    "ivy","iyana","iyanna","iyla","iyonna","izaac","izaak","izabel","izabella","izabelle",
    "izaiah","izak","izamar","izan","izayah","izel","izzabella","jabari","jabez","jacalyn",
    "jacari","jace","jacelyn","jacen","jaceon","jacey","jaceyon","jaci","jacie","jacinda",
    "jacinta","jack","jackeline","jackelyn","jacki","jackie","jacklyn","jackson","jacky","jaclyn",
    "jacob","jacobi","jacoby","jacorey","jacque","jacqueli","jacquelin","jacqueline","jacquelyn","jacquelynn",
    "jacques","jacquez","jacquline","jacy","jad","jada","jadah","jade","jadelyn","jaden",
    "jadiel","jadin","jadon","jadyn","jaeda","jaeden","jaedon","jaedyn","jael","jaela",
    "jaelyn","jaelynn","jagger","jaheem","jaheim","jahiem","jahir","jahlil","jahmir","jahseh",
    "jahzara","jai","jaiceon","jaida","jaiden","jaidon","jaidyn","jaila","jailene","jailyn",
    "jailyne","jailynn","jaime","jaimee","jaimie","jaina","jair","jairo","jajuan","jakai",
    "jakari","jakayla","jake","jakiya","jakob","jakobe","jakobi","jakoby","jakub","jala",
    "jalani","jalaya","jalayah","jaleah","jaleel","jaleesa","jalen","jalessa","jalia","jalil",
    "jalin","jalisa","jalissa","jaliyah","jalon","jalyn","jalynn","jalyssa","jamaal","jamal",
    "jamar","jamarcus","jamari","jamarion","jamaya","jameel","jameer","jameka","jamel","james",
    "jamesha","jameson","jamey","jami","jamia","jamiah","jamie","jamika","jamil","jamila",
    "jamin","jamir","jamison","jamiya","jamiyah","jammie","jamya","jan","jana","janae",
    "janai","janay","janaya","jancarlos","jane","janee","janeen","janel","janell","janelle",
    "janelly","janely","janene","janessa","janet","janeth","janette","janey","jania","janiah",
    "janice","janie","janine","janis","janiya","janiyah","jann","janna","jannah","jannat",
    "jannette","janney","jannie","january","janya","janyla","jaquan","jaquelin","jaqueline","jaquelyn",
    "jaquez","jarad","jared","jarell","jaren","jaret","jarett","jariel","jarod","jaron",
    "jarred","jarrell","jarren","jarret","jarrett","jarrod","jarvis","jase","jasen","jashawn",
    "jasiah","jasiel","jasir","jasleen","jaslene","jaslyn","jaslynn","jasmin","jasmine","jasmyn",
    "jasmyne","jason","jasper","jaunita","javan","javen","javeon","javian","javien","javier",
    "javin","javion","javon","javonte","jawan","jax","jaxen","jaxon","jaxsen","jaxson",
    "jaxton","jaxtyn","jaxx","jaxxon","jaxyn","jay","jaya","jayce","jaycee","jayceon",
    "jaycie","jaycion","jaycob","jayda","jaydah","jaydan","jayde","jayden","jaydin","jaydon",
    "jaye","jayla","jaylah","jaylan","jaylani","jaylee","jayleen","jayleigh","jaylen","jaylene",
    "jaylin","jaylon","jaylyn","jaylynn","jayme","jaymes","jaymie","jayna","jayne","jayquan",
    "jayse","jaysen","jayshawn","jayson","jayven","jayveon","jayvion","jayvon","jazelle","jaziel",
    "jazleen","jazlene","jazlyn","jazlynn","jazmin","jazmine","jazmyn","jazmyne","jazzlyn","jazzlynn",
    "jazzmin","jazzmine","jean","jeana","jeancarlos","jeane","jeanetta","jeanette","jeanie","jeanine",
    "jeanmarie","jeanna","jeanne","jeannette","jeannie","jeannine","jed","jedediah","jedidiah","jeff",
    "jefferey","jefferson","jeffery","jeffrey","jeffry","jelani","jelisa","jemal","jemma","jena",
    "jenae","jencarlos","jenelle","jenesis","jenessa","jeni","jenifer","jeniffer","jenilee","jenna",
    "jennah","jenni","jennie","jennifer","jenniffer","jennings","jenny","jensen","jenson","jerad",
    "jerald","jeraldine","jeramiah","jeramie","jeramy","jere","jered","jerel","jereme","jeremey",
    "jeremiah","jeremias","jeremie","jeremih","jeremy","jeri","jerica","jericho","jerika","jerilyn",
    "jerilynn","jerimiah","jermain","jermaine","jermey","jermiah","jerod","jerold","jerome","jeromy",
    "jerrad","jerrell","jerri","jerrica","jerrie","jerrod","jerrold","jerry","jersey","jeryl",
    "jesenia","jeshua","jesiah","jesica","jeslyn","jess","jessa","jessalyn","jesse","jessenia",
    "jessi","jessiah","jessica","jessie","jessika","jesslyn","jessy","jesus","jet","jethro",
    "jett","jettie","jevon","jewel","jewell","jhene","jhett","jia","jianna","jill",
    "jillian","jim","jimena","jimmie","jimmy","jionni","jiovanni","jiraiya","jiselle","jiya",
    "jizelle","jkwon","jo","joan","joana","joanie","joann","joanna","joanne","joaquin",
    "jocelin","joceline","jocelyn","jocelyne","jocelynn","jodee","jodi","jodie","jody","joe",
    "joel","joell","joelle","joellen","joesph","joetta","joette","joey","johan","johana",
    "johann","johanna","johannah","johathan","john","johnathan","johnathon","johnie","johnna","johnnie",
    "johnny","johnpaul","johnson","joi","jolee","joleen","jolene","jolette","jolie","jolynn",
    "jomar","jon","jonael","jonah","jonas","jonatan","jonathan","jonathon","jonelle","jones",
    "joni","jonna","jonnie","jordan","jorden","jordi","jordin","jordon","jordy","jordyn",
    "jordynn","joretta","jorge","jorja","jory","josalyn","joscelyn","jose","josef","josefina",
    "joselin","joseline","joseluis","joselyn","joselyne","joseph","josephina","josephine","josette","josey",
    "josh","joshua","joshuah","josiah","josias","josie","joslyn","joslynn","josselyn","josslyn",
    "josue","jourdan","journee","journei","journey","journi","journie","jovan","jovana","jovani",
    "jovanna","jovanni","jovanny","jovany","jovi","jovie","joy","joyce","joycelyn","joziah",
    "jream","jrue","juan","juana","juancarlos","juanita","juanpablo","jubilee","judah","judd",
    "jude","judi","judie","judith","judson","judy","juelz","julee","jules","juli",
    "julia","julian","juliana","juliann","julianna","julianne","julie","julien","juliet","julieta",
    "julietta","juliette","julio","julisa","julissa","julius","jullian","june","junior","juniper",
    "junius","juno","jupiter","jurnee","justen","justice","justin","justina","justine","juston",
    "justus","justyce","justyn","juwan","kaaren","kabir","kace","kacen","kacey","kaci",
    "kacie","kacy","kadance","kade","kadeem","kadejah","kaden","kadence","kadesha","kadie",
    "kadijah","kadin","kady","kadyn","kaeden","kaedyn","kael","kaela","kaelani","kaeli",
    "kaelin","kaelyn","kaelynn","kahlan","kahlani","kahlil","kai","kaia","kaiden","kaidence",
    "kaidyn","kaila","kailani","kailany","kailee","kaileigh","kailey","kaili","kaily","kailyn",
    "kailynn","kain","kaine","kainen","kainoa","kaira","kairi","kairo","kaisen","kaiser",
    "kaisley","kaison","kaitlan","kaitlin","kaitlyn","kaitlynn","kaius","kaiya","kaizen","kaizer",
    "kala","kalani","kale","kalea","kaleah","kaleb","kalee","kaleena","kalei","kaleigh",
    "kalel","kalen","kalene","kaleo","kaley","kali","kalia","kaliah","kalie","kalina",
    "kalista","kaliyah","kallen","kalli","kallie","kalob","kalvin","kalyn","kalynn","kamala",
    "kamari","kamaria","kamarion","kamaya","kambree","kamden","kamdyn","kameron","kameryn","kami",
    "kamiah","kamila","kamilah","kamilla","kamille","kamiya","kamiyah","kamora","kamren","kamron",
    "kamryn","kamya","kanan","kandace","kandi","kandice","kandis","kandy","kane","kaneesha",
    "kaneisha","kanesha","kanisha","kaniya","kaniyah","kannon","kanon","kanye","kapri","kara",
    "karah","karam","karan","kareem","karely","karen","karena","karey","kari","karie",
    "karim","karime","karin","karina","karis","karisa","karissa","karizma","karl","karla",
    "karlee","karleigh","karlene","karley","karli","karlie","karly","karma","karmen","karmyn",
    "karol","karolina","karoline","karolyn","karon","karren","karri","karrie","karsen","karson",
    "karsten","karsyn","karter","kartier","karyme","karyn","kasandra","kase","kasen","kasey",
    "kash","kashmir","kashton","kasi","kasie","kason","kassandra","kassi","kassidy","kassie",
    "kassius","kasyn","kataleya","katalina","katarina","kate","katelin","katelyn","katelynn","katerina",
    "katey","kathaleen","katharine","katherin","katherine","katheryn","kathey","kathi","kathie","kathleen",
    "kathlene","kathlyn","kathrine","kathryn","kathryne","kathy","kathyrn","kati","katia","katie",
    "katilyn","katina","katlin","katlyn","katlynn","katrina","katy","katya","kavion","kavon",
    "kavya","kay","kaya","kayce","kaycee","kaycen","kaydance","kaydee","kayden","kaydence",
    "kaydin","kaye","kayla","kaylah","kaylan","kaylani","kayle","kaylea","kayleb","kaylee",
    "kayleen","kaylei","kayleigh","kaylen","kaylene","kayley","kayli","kaylie","kaylin","kaylyn",
    "kaylynn","kayne","kaysen","kayson","kaytlin","kaytlyn","keagan","keana","keandre","keanna",
    "keanu","keara","kearra","keasia","keaton","kecia","keegan","keelan","keeley","keely",
    "keena","keenan","keenen","keesha","kegan","kehlani","keifer","keila","keilani","keily",
    "keion","keira","keisha","keith","kejuan","kelan","kelani","kelby","kelcey","kelci",
    "kelcie","keli","kelis","kellan","kelle","kellee","kellen","keller","kelley","kelli",
    "kellie","kellin","kelly","kellye","kelsea","kelsee","kelsey","kelsi","kelsie","kelsy",
    "kelton","kelvin","kemari","ken","kenadee","kenadi","kenadie","kenai","kenan","kendal",
    "kendall","kendell","kendra","kendrick","kendyl","kendyll","kenia","kenisha","kenji","kenlee",
    "kenleigh","kenley","kenna","kennadi","kennady","kennedi","kennedy","kenneth","kennith","kenny",
    "kensington","kenslee","kensley","kent","kenton","kentrell","kenya","kenyatta","kenyetta","kenyon",
    "kenzi","kenzie","kenzlee","kenzley","kenzo","keon","keona","keoni","keosha","kera",
    "keren","keri","kermit","kerri","kerrie","kerrigan","kerry","kesha","keshaun","keshawn",
    "keshia","keshon","keven","kevin","kevon","kevyn","keyana","keyanna","keyara","keyla",
    "keylee","keyon","keyona","keyonna","keyshawn","keziah","khadejah","khadija","khadijah","khai",
    "khalani","khaled","khaleesi","khali","khalia","khalid","khalil","khalilah","khamani","khamari",
    "khari","khaza","khiry","khloe","khloee","khloey","khloie","khristian","khushi","khyree",
    "kia","kiaan","kiah","kian","kiana","kianna","kiara","kiarra","kiefer","kiel",
    "kiera","kieran","kierra","kiersten","kierstin","kierstyn","kiesha","kilee","kiley","kilian",
    "killian","kim","kimani","kimber","kimberely","kimberlee","kimberley","kimberli","kimberlie","kimberly",
    "kimberlyn","kimora","kindra","king","kingsley","kingston","kinlee","kinleigh","kinley","kinsey",
    "kinslee","kinsleigh","kinsley","kinte","kinzlee","kinzley","kion","kip","kipton","kiptyn",
    "kira","kiran","kirby","kirk","kirkland","kirra","kirsten","kirsti","kirstie","kirstin",
    "kirstyn","kirt","kisha","kit","kitty","kiya","kiyah","kiyan","kiyomi","kizzie",
    "kizzy","klaire","klara","klarissa","klayton","kloe","kloey","kloie","knowledge","knox",
    "koa","kobe","kobi","kobie","koby","koda","kodi","kody","koen","kohen",
    "kolbe","kolby","kole","kollin","kolson","kolt","kolten","kolton","konner","konnor",
    "kooper","kora","korben","korbin","korbyn","kordell","korey","kori","korie","korina",
    "korra","kortney","kory","kourtney","kraig","krew","kris","krish","krissy","krista",
    "kristal","kristan","kristel","kristen","kristi","kristian","kristiana","kristie","kristin","kristina",
    "kristine","kristofer","kristoffer","kristopher","kristy","kristyn","kross","krue","kruz","krysta",
    "krystal","krysten","krystin","krystina","krystle","kunta","kurt","kurtis","kwame","kya",
    "kyah","kyaire","kyan","kyana","kyanna","kyara","kyden","kye","kyjuan","kyla",
    "kylah","kylan","kylar","kyle","kylee","kyleigh","kylen","kylene","kyler","kyli",
    "kylian","kylie","kylin","kylo","kymani","kymberly","kyndal","kyndall","kyndra","kyng",
    "kyngston","kynlee","kynleigh","kynnedi","kynslee","kynzlee","kyomi","kyra","kyrah","kyran",
    "kyree","kyren","kyrie","kyrin","kyro","kyron","kyrsten","kysen","kyson","kyzer",
    "lacee","lacey","lachlan","laci","lacie","lacy","ladarius","ladonna","laela","lahoma",
    "laikyn","laila","lailah","lailani","laina","laine","lainey","laisha","laith","laiyah",
    "lakeesha","lakeisha","lakelyn","lakelynn","laken","lakendra","lakesha","lakeshia","lakia","lakiesha",
    "lakisha","lakita","lakyn","lamar","lamarion","lamonica","lamont","lamya","lana","lance",
    "landan","landen","landin","landon","landry","landyn","lane","lanette","laney","langston",
    "lani","lanie","lanita","laniya","laniyah","lannie","lanny","laquan","laquisha","laquita",
    "lara","laraine","larhonda","lariah","larisa","larissa","larkin","laron","laronda","larry",
    "lars","larue","lashae","lashanda","lashanti","lashaunda","lashawn","lashawnda","lashay","lashon",
    "lashonda","lashunda","lasonya","latanya","latara","latarsha","latasha","latashia","latavia","latesha",
    "lathan","latia","laticia","latifah","latisha","latonia","latonya","latoria","latosha","latoya",
    "latoyia","latrell","latrice","latricia","latrina","latrisha","laura","laure","laureen","laurel",
    "lauren","laurence","laurene","lauretta","lauri","laurie","lauryn","lavada","lavar","lavender",
    "lavern","laverna","laverne","lavina","lavon","lavonda","lavonne","lawanda","lawerence","lawrence",
    "lawson","laya","layan","layla","laylah","laylani","layna","layne","laynee","layton",
    "lazaro","lazarus","lea","leah","leana","leandra","leandro","leann","leanna","leanne",
    "leatha","leatrice","lebron","ledger","lee","leeann","leeanna","leela","leeland","leen",
    "leena","leesa","leeza","legaci","legacy","legend","leia","leif","leigh","leigha",
    "leighann","leighton","leila","leilah","leilani","leilany","leisa","leisha","lela","leland",
    "lelia","lemuel","len","lena","lenard","leni","lenna","lennie","lennon","lennox",
    "lenny","lenora","lenore","lenox","leo","leola","leon","leona","leonard","leonardo",
    "leone","leonel","leonidas","leonora","leopold","leora","leota","leroy","les","lesa",
    "lesia","leslee","lesley","lesli","leslie","lesly","lessie","lester","leta","letha",
    "leticia","letisha","letitia","lettie","letty","lev","levar","levi","levon","lewis",
    "lexa","lexi","lexie","lexis","lexus","lexy","leyla","leylani","leyna","leyton",
    "lia","liah","liam","lian","liana","liane","lianna","libby","liberty","lida",
    "lidia","liesl","lila","lilah","lili","lilia","lilian","liliana","lilianna","lilibeth",
    "lilith","lilli","lillian","lilliana","lillianna","lillie","lillith","lilly","lillyan","lillyana",
    "lillyann","lillyanna","lily","lilyan","lilyana","lilyann","lilyanna","lilyanne","lina","lincoln",
    "linda","lindbergh","linden","lindsay","lindsey","lindsy","lindy","linette","link","linkin",
    "linnea","linnie","linsey","linus","linwood","lionel","lisa","lisandro","lisbet","lisbeth",
    "lise","lisette","lisha","lissa","lisset","lissette","lita","litzy","liv","livia",
    "liya","liyah","liyana","liz","liza","lizabeth","lizbet","lizbeth","lizet","lizeth",
    "lizette","lizzie","lloyd","lluvia","lochlan","logan","lois","loki","lola","lolita",
    "lon","lona","london","londyn","londynn","long","loni","lonnie","lonny","lora",
    "loraine","loralei","loree","loreen","lorelai","lorelei","loren","lorena","lorene","lorenzo",
    "loretta","lori","loria","loriann","lorie","lorin","lorinda","lorine","lorna","lorne",
    "lorraine","lorri","lorrie","lory","lottie","lotus","lou","louann","louella","louie",
    "louis","louisa","louise","lourdes","love","lovie","lowell","loyal","loyalty","loyce",
    "loyd","lu","luana","luann","luanne","luc","luca","lucas","lucca","lucero",
    "lucia","lucian","luciana","lucianna","luciano","lucie","lucien","lucile","lucille","lucinda",
    "lucio","lucius","lucretia","lucy","lue","luella","luis","luisa","luisana","luiz",
    "luka","lukas","luke","lula","lulu","luna","lupe","lupita","lura","luther",
    "lux","luz","lyam","lyanna","lyda","lydia","lyla","lylah","lyle","lyman",
    "lyn","lynda","lyndon","lyndsay","lyndsey","lynette","lynlee","lynn","lynne","lynnette",
    "lynsey","lynwood","lyra","lyric","lyrica","lyrik","mabel","mable","mac","macarthur",
    "macayla","macey","machelle","maci","macie","mack","mackenna","mackenzi","mackenzie","macklin",
    "macy","madaline","madalyn","madalynn","madden","maddex","maddie","maddilyn","maddison","maddix",
    "maddox","maddux","madelaine","madeleine","madelin","madeline","madelyn","madelyne","madelynn","madelynne",
    "madge","madie","madilyn","madilynn","madisen","madison","madisyn","madonna","madysen","madyson",
    "mae","maegan","maelyn","maelynn","maeve","magali","magaly","magan","magdalena","magdalene",
    "magen","maggie","magnolia","magnus","mahi","mahogany","mai","maia","maile","maira",
    "maisha","maisie","maison","maisy","maisyn","maite","maiya","maizie","majesty","major",
    "makaela","makai","makaila","makala","makalah","makari","makayla","makaylah","makaylee","makena",
    "makenna","makenzi","makenzie","makenzy","makhi","makiah","makinley","makiya","makiyah","maksim",
    "makyla","malachi","malak","malakai","malakhi","malaki","malani","malaya","malayah","malayna",
    "malaysia","malcolm","malcom","male","malea","maleah","maleigha","malek","malena","maleni",
    "malia","maliah","maliha","malik","malika","malikai","malina","malinda","malique","malisa",
    "malissa","maliya","maliyah","malka","malky","mallorie","mallory","malorie","mamie","manda",
    "mandi","mandie","mandy","manila","manny","manuel","manuela","maple","mara","marah",
    "maranda","marc","marcanthony","marcel","marcela","marceline","marcelino","marcell","marcella","marcelle",
    "marcello","marcellus","marcelo","marchello","marci","marcia","marcie","marco","marcos","marcus",
    "marcy","marek","mareli","marely","maren","margaret","margarett","margarette","margarita","margaux",
    "marge","margery","margie","margo","margot","margret","marguerite","marguita","mari","maria",
    "mariah","mariajose","mariam","marian","mariana","mariann","marianna","marianne","mariano","maribel",
    "maribeth","maricela","maricruz","marie","mariel","mariela","marielena","mariella","marielle","marietta",
    "marigold","marilee","marilyn","marilynn","marimar","marin","marina","mario","marion","marisa",
    "marisela","mariska","marisol","marissa","marita","maritza","mariya","mariyah","marjorie","marjory",
    "mark","markayla","markeisha","markel","markell","markie","markita","marko","markus","marla",
    "marlana","marlee","marleen","marleigh","marlen","marlena","marlene","marley","marli","marlie",
    "marlin","marlo","marlon","marlow","marlowe","marlyn","marlys","marni","marnie","marnita",
    "marquel","marques","marquez","marquis","marquise","marquita","marquitta","marsha","marshall","marshawn",
    "marta","martell","martez","martha","marti","martika","martin","martina","martine","marty",
    "marva","marvel","marvin","marwa","mary","maryah","maryam","maryann","maryanne","marybeth",
    "maryellen","maryjane","maryjo","marylin","marylou","marylyn","maryn","masen","mason","massiah",
    "massimo","masyn","mateo","matheo","matheus","mathew","mathias","mathilda","mathis","matias",
    "matilda","matt","mattea","matteo","matthew","matthias","mattias","mattie","mattison","maud",
    "maude","maudie","maura","maureen","maurice","mauricio","maurine","mauro","maverick","maverik",
    "mavis","mavrick","max","maxie","maxim","maximilian","maximiliano","maximillian","maximo","maximus",
    "maxine","maxon","maxton","maxwell","maxx","may","maya","mayah","maybelle","maycee",
    "maylee","maylin","mayme","maynard","mayra","mayrin","mayson","mayte","mazi","mazie",
    "mazikeen","mcarthur","mccoy","mckayla","mckenna","mckenzie","mckinlee","mckinley","mea","meadow",
    "meagan","meaghan","meah","mechelle","meera","meg","megan","meggan","meghan","meghann",
    "mehki","meilani","meir","mekayla","mekhi","mel","melani","melania","melanie","melany",
    "melba","melia","melina","melinda","melisa","melissa","melissia","mellisa","mellissa","melodee",
    "melodie","melody","melonie","melony","melva","melvin","melvina","melvyn","melynda","melyssa",
    "memphis","menachem","mendy","meranda","mercedes","mercedez","mercy","meredith","merida","meridith",
    "merissa","merle","merlin","merlyn","merri","merrick","merrie","merrill","merrily","merritt",
    "merry","merton","mervin","meryl","messiah","meta","meyer","mia","miabella","miah",
    "mica","micaela","micah","micaiah","micayla","michael","michaela","michaele","michaella","michala",
    "michayla","micheal","micheala","michel","michele","michell","michelle","mickayla","mickey","mickie",
    "miesha","migdalia","miguel","miguelangel","mika","mikael","mikaela","mikah","mikaila","mikal",
    "mikala","mikalah","mikayla","mikaylah","mike","mikel","mikhail","mila","milagros","milah",
    "milan","milana","milani","milania","mildred","mileena","milena","miles","miley","milford",
    "milissa","milla","millard","miller","millicent","millie","milly","milo","milton","mimi",
    "mina","mindi","mindy","minerva","minnie","mira","miracle","miranda","mirella","mireya",
    "mirha","miriah","miriam","mirian","mirna","misael","mischa","misha","missy","misti",
    "mistie","misty","mitch","mitchel","mitchell","mittie","mitzi","miya","miyah","moana",
    "moesha","mohamad","mohamed","mohammad","mohammed","moira","moises","mollie","molly","mona",
    "monae","monet","monica","monika","monique","monroe","monserrat","montana","monte","montel",
    "montez","montgomery","montrell","montserrat","monty","mordechai","morgan","moriah","morris","morton",
    "mose","moses","moshe","mozell","mozelle","muhammad","muhammed","muriel","murphy","murray",
    "musa","mustafa","mya","myah","mychal","myesha","myia","myka","mykala","mykayla",
    "mykel","myla","mylah","mylee","myleigh","myles","mylie","mylo","myra","myranda",
    "myriah","myriam","myrna","myron","myrtice","myrtie","myrtis","myrtle","nadia","nadine",
    "nadya","nahla","nahomi","naia","naila","nailah","nailea","naima","nairobi","naja",
    "najah","najee","nakayla","nakia","nakisha","nakita","nakiya","nala","nalani","nallely",
    "nan","nanci","nancie","nancy","nanette","nannette","nannie","naomi","naomy","napoleon",
    "nariah","nariyah","nash","nasir","natalee","natali","natalia","natalie","nataly","natalya",
    "natanael","natasha","natashia","nate","nathalia","nathalie","nathaly","nathan","nathanael","nathanial",
    "nathaniel","nathen","natisha","natosha","nautica","navaeh","naveah","navi","navy","navya",
    "naya","naydelin","nayeli","nayelli","nayely","nayla","nazir","neal","nechama","ned",
    "nedra","neel","neela","neha","nehemiah","nehemias","neida","neil","nelda","nell",
    "nelle","nellie","nelly","nelson","nena","neo","neoma","nereida","neriah","nery",
    "nestor","nettie","neva","nevaeh","nevaeha","neveah","nevin","newton","neymar","nia",
    "niam","nichelle","nichol","nicholas","nicholaus","nichole","nick","nicki","nickie","nicklas",
    "nicklaus","nickolas","nickole","nicky","nico","nicol","nicola","nicolas","nicole","nicolette",
    "nicolle","nicollette","niesha","nigel","nikhil","niki","nikia","nikita","nikki","nikko",
    "niklaus","niko","nikola","nikolai","nikolas","nikole","nila","nilda","nina","nira",
    "nirvana","nisha","nita","nixon","niya","niyah","noa","noah","noam","noble",
    "noe","noel","noelani","noelia","noella","noelle","noemi","nohely","nola","nolan",
    "nolen","nona","noor","nora","norah","norbert","norberto","noreen","norene","nori",
    "norine","norita","norma","norman","normand","norris","notnamed","nour","nova","novah",
    "novalee","novaleigh","novella","nuri","nya","nyah","nyasia","nyla","nylah","nyomi",
    "nyra","nyree","nyssa","oakland","oaklee","oakleigh","oakley","oaklyn","oaklynn","obadiah",
    "obed","ocean","ocie","octavia","octavio","octavius","odalis","odalys","odell","odessa",
    "odette","odin","odis","ofelia","ola","olen","oleta","olga","olin","olive",
    "oliver","olivia","ollie","olympia","olyvia","om","oma","omar","omari","omarion",
    "omer","ona","onyx","oona","opal","ophelia","ora","oralia","oran","oren",
    "oriana","orin","orion","orlando","orpha","orson","orval","orville","osbaldo","oscar",
    "oseias","osiel","osiris","oskar","osman","osmar","osvaldo","oswald","oswaldo","otha",
    "otho","otis","ottis","otto","ouida","owen","ozias","oziel","ozzy","pa",
    "pablo","page","paige","paislee","paisleigh","paisley","paiton","paityn","paizlee","paizley",
    "palma","palmer","paloma","pam","pamala","pamela","pamelia","pamella","pandora","pansy",
    "paola","paolo","paris","parker","parrish","pasquale","pat","patience","patric","patrica",
    "patrice","patricia","patricio","patrick","patsy","patti","pattie","patty","paul","paula",
    "pauletta","paulette","paulina","pauline","paulo","paxton","payne","payson","payten","payton",
    "pearl","pearle","pearlie","pearline","pedro","peggie","peggy","peighton","penelope","penney",
    "penni","pennie","penny","pepper","percy","perla","pernell","perri","perry","persephone",
    "perseus","pershing","pete","peter","petra","peyton","pharaoh","phil","philip","phillip",
    "phillis","philomena","phineas","phoebe","phoenix","phylicia","phylis","phyllis","pia","pierce",
    "pierre","pierson","pilar","piper","pippa","polly","pooja","poppy","porscha","porsche",
    "porsha","porter","portia","pranav","precious","preslee","presleigh","presley","preslie","preston",
    "pricilla","prince","princess","princeton","priscila","priscilla","prisha","priya","promise","prudence",
    "pyper","qiana","quanisha","queen","quentin","quenton","quiana","quincy","quinlan","quinn",
    "quinten","quintin","quinton","rachael","racheal","rachel","rachele","rachelle","racquel","rae",
    "raeann","raechel","raegan","raekwon","raelee","raeleigh","raelyn","raelynn","rafael","raheem",
    "rahsaan","rahul","raiden","rain","raina","raine","raizy","rakeem","raleigh","ralph",
    "rami","ramiro","ramiyah","ramon","ramona","ramses","ramsey","rana","ranada","rand",
    "randa","randal","randall","randel","randell","randi","randolph","randy","ranger","rania",
    "raniya","raniyah","ransom","raphael","raquan","raquel","rashaad","rashaan","rashad","rashaun",
    "rashawn","rasheda","rasheed","rasheeda","rasheedah","rashida","raul","raven","ravyn","ray",
    "raya","rayan","rayanna","rayden","rayford","raylan","raylee","rayleigh","raylen","raylynn",
    "raymon","raymond","raymundo","rayna","raynard","rayne","rayshawn","rayven","rayyan","reagan",
    "reanna","reba","rebeca","rebecca","rebeccah","rebecka","rebekah","rebel","reece","reed",
    "reem","reese","regan","regenia","reggie","regina","reginald","regine","reid","reign",
    "reilly","reina","remi","remington","remy","ren","rena","renada","renae","renaldo",
    "renata","rene","renea","renee","renesmee","renita","reno","renzo","reta","retha",
    "reuben","reva","rex","rey","reya","reyansh","reyes","reyli","reyna","reynaldo",
    "rhea","rheta","rhett","rhianna","rhiannon","rhoda","rhodes","rhonda","rhyan","rhylee",
    "rhys","ria","riaan","rian","riana","rianna","ricardo","rich","richard","richelle",
    "richie","rick","rickey","ricki","rickie","ricky","rico","ridge","ridley","riggs",
    "rigoberto","rihanna","rikki","rilee","rileigh","riley","rilyn","rilynn","rio","ripley",
    "ripp","risa","rishaan","rishi","rita","ritchie","river","riverlyn","rivka","rivky",
    "riya","roan","rob","robb","robbie","robbin","robby","robert","roberta","roberto",
    "robin","robyn","rocco","rochel","rochelle","rocio","rock","rockwell","rocky","rod",
    "roderick","rodger","rodney","rodolfo","rodrick","rodrigo","rogan","rogelio","roger","rogers",
    "rohan","rohit","roland","rolanda","rolando","rolland","rollin","roma","roman","romario",
    "rome","romello","romeo","romina","romona","romy","ron","rona","ronald","ronaldo",
    "ronan","ronda","roni","ronin","ronisha","ronna","ronnie","ronny","roosevelt","rori",
    "rory","rosa","rosabella","rosalba","rosalee","rosaleigh","rosalia","rosalie","rosalina","rosalind",
    "rosalinda","rosalyn","rosalynn","rosamond","rosann","rosanna","rosanne","rosario","roscoe","rose",
    "roseann","roseanna","roseanne","rosella","roselyn","roselynn","rosemarie","rosemary","rosetta","rosevelt",
    "rosia","rosie","rosina","rosio","rosita","roslyn","ross","rowan","rowdy","rowen",
    "rowena","rowyn","roxana","roxane","roxann","roxanna","roxanne","roxie","roxy","roy",
    "royal","royalty","royce","ruben","rubi","rubie","rubin","ruby","rubye","rudolph",
    "rudra","rudy","rufus","ruger","ruhi","rupert","russ","russel","russell","rusty",
    "ruth","ruthann","ruthe","ruthie","ryan","ryann","ryanne","ryatt","ryden","ryder",
    "ryker","rylan","ryland","rylee","ryleigh","rylen","ryley","rylie","rylin","rylynn",
    "ryne","ryu","saanvi","sabastian","sabina","sabine","sable","sabra","sabrena","sabrina",
    "sacha","sade","sadie","safa","safiya","sage","sahana","sahara","sahasra","sahil",
    "said","saif","saige","sailor","saint","saira","sal","salem","salena","salina",
    "sallie","sally","salma","salman","salome","salvador","salvatore","sam","sama","samaira",
    "samantha","samara","samarah","samaria","samatha","samaya","sameer","sami","samia","samir",
    "samira","samiya","samiyah","sammantha","sammie","sammy","samone","samson","samual","samuel",
    "samya","sana","sanaa","sanai","sanaya","sandi","sandie","sandra","sandy","sanford",
    "sania","saniah","saniya","saniyah","sanjana","sanjuana","sanjuanita","santana","santiago","santino",
    "santo","santos","sanvi","sanya","saoirse","saphira","sapphire","sara","sarabeth","sarah",
    "sarahi","sarai","saray","sariah","sarina","sarita","sariya","sariyah","sasha","saul",
    "saundra","savana","savanah","savanna","savannah","savion","savon","sawyer","saydee","saylor",
    "sayuri","scarlet","scarlett","scarlette","schuyler","scot","scott","scottie","scotty","scout",
    "seamus","sean","seanna","season","sebastian","sebastien","sebrina","sedrick","sekani","selah",
    "selena","selene","selina","selma","semaj","seneca","sequoia","serafina","seraphina","serena",
    "serenity","sergio","serina","seth","seven","sevyn","seymour","shaan","shad","shae",
    "shaelyn","shai","shaila","shaina","shakayla","shakera","shakia","shakira","shakiyla","shakur",
    "shalanda","shalon","shalonda","shamar","shameka","shamika","shamya","shana","shanae","shanay",
    "shanaya","shanda","shandi","shandra","shane","shanee","shaneka","shanel","shanell","shanelle",
    "shanequa","shani","shania","shaniah","shanice","shaniece","shanika","shaniqua","shanique","shanise",
    "shanita","shaniya","shaniyah","shanna","shannan","shannen","shannon","shanon","shanta","shante",
    "shantel","shantell","shantelle","shanya","shaquan","shaquana","shaquilla","shaquille","shaquita","shara",
    "sharda","shardae","sharday","sharde","sharee","sharen","shari","sharina","sharita","sharla",
    "sharleen","sharlene","sharman","sharon","sharonda","sharron","sharyl","sharyn","shasta","shatara",
    "shaun","shauna","shaunda","shaunna","shaunta","shaunte","shaurya","shavon","shavonne","shawana",
    "shawanda","shawn","shawna","shawnda","shawnee","shawnna","shawnta","shawnte","shay","shaya",
    "shaye","shayla","shaylee","shaylynn","shayna","shayne","shea","sheena","sheila","sheilah",
    "shekinah","shelba","shelbi","shelbie","shelby","sheldon","shelia","shelley","shelli","shellie",
    "shelly","shelton","shelva","shemar","shemeka","shemika","shena","shenika","shenna","shepard",
    "shepherd","shequita","shera","sheree","sheri","sheridan","sherie","sherika","sherilyn","sherita",
    "sherlin","sherlyn","sherman","sheron","sherree","sherri","sherrie","sherrill","sherron","sherry",
    "sherryl","sherwood","sheryl","sheryll","sheyenne","sheyla","shia","shiann","shianne","shiela",
    "shiloh","shimon","shira","shirl","shirlee","shirlene","shirley","shivani","shivansh","shlomo",
    "shmuel","shon","shona","shonda","shonna","shonta","shoshana","shreya","shriya","shyann",
    "shyanne","shyheim","shyla","shylah","sia","sibyl","siddharth","sidney","siena","sienna",
    "siera","sierra","sigmund","silas","silvia","simeon","simon","simone","simran","sinai",
    "sincere","sinead","siobhan","sir","sire","sirena","siri","siya","skip","sky",
    "skye","skyla","skylah","skylar","skylee","skyler","skylynn","skyy","slade","sloan",
    "sloane","smith","socorro","sofia","sofie","sol","solana","solange","soleil","solomon",
    "somaya","somer","sommer","sondra","sonia","sonja","sonji","sonny","sonya","sophia",
    "sophie","soraya","soren","sparkle","spencer","spenser","spring","stacey","staci","stacia",
    "stacie","stacy","stan","stanford","stanley","stanton","star","starla","starr","steele",
    "stefan","stefani","stefanie","stefany","steffanie","stella","stellan","stephaine","stephan","stephani",
    "stephanie","stephany","stephen","stephenie","stephon","sterling","stetson","stevan","steve","steven",
    "stevie","stewart","stone","stoney","storm","stormi","stormie","stormy","story","stryker",
    "stuart","sue","suellen","sullivan","sultan","sumaya","summer","sunday","sunny","sunshine",
    "suri","susan","susana","susann","susanna","susannah","susanne","susie","sutton","suzan",
    "suzann","suzanna","suzanne","suzette","suzie","suzy","sybil","syble","sydnee","sydney",
    "sydni","sydnie","syed","sylas","sylvan","sylvester","sylvia","sylvie","symone","symphony",
    "syncere","syreeta","syriana","tab","tabatha","tabetha","tabitha","tad","tadeo","taelor",
    "taelyn","taelynn","taha","tahiry","tahj","tahlia","tai","taina","taisha","taj",
    "taja","takisha","takoda","tala","talan","taleah","talen","talia","taliah","talisa",
    "talisha","taliyah","tallulah","talmadge","talon","talya","tamala","tamar","tamara","tamatha",
    "tambra","tameika","tameka","tamekia","tamela","tamera","tami","tamia","tamica","tamie",
    "tamika","tamiko","tamir","tamisha","tamiya","tammara","tammi","tammie","tammy","tamra",
    "tamya","tamyra","tana","tanaya","taneisha","taneka","tanesha","tangela","tania","tanika",
    "tanisha","taniya","taniyah","tanja","tanner","tanvi","tanya","tara","tarah","taraji",
    "taran","tari","tarik","tariq","tarra","tarrah","tarsha","taryn","tasha","tashia",
    "tashina","tasia","tatanisha","tate","tatia","tatiana","tatianna","tatiyana","tatum","tatyana",
    "tatyanna","taunya","taurean","taurus","tavares","tavaris","taven","tavia","tavian","tavin",
    "tavion","tavon","tawana","tawanda","tawanna","tawni","tawny","tawnya","taya","tayah",
    "tayden","tayla","taylar","taylee","taylen","tayler","taylin","taylor","tayshaun","tayshawn",
    "taysom","taytum","tea","teagan","teanna","ted","teddy","teegan","teela","teena",
    "tegan","tehya","teigan","telly","telvin","temeka","temperance","tena","tenika","tenille",
    "tenisha","tenley","tennille","teo","tequila","tera","terell","terence","teresa","terese",
    "teressa","teri","terra","terrance","terrell","terrence","terri","terrie","terrill","terry",
    "tesla","tess","tessa","tessie","tevin","thad","thaddeus","thalia","thatcher","thea",
    "theda","theia","thelma","theo","theodora","theodore","theresa","therese","theron","thiago",
    "thomas","thor","thorin","thurman","tia","tiago","tiana","tianna","tiara","tiarra",
    "tiberius","tiera","tierney","tierra","tiesha","tiffaney","tiffani","tiffanie","tiffany","tiffiny",
    "tiger","tillie","tilly","tim","timmie","timmothy","timmy","timothy","tina","tinley",
    "tinsley","tionna","tionne","tisa","tisha","titan","titus","tkeyah","tobi","tobias",
    "tobin","toby","toccara","tod","todd","tom","tomas","tomeka","tomika","tommie",
    "tommy","tonda","toney","toni","tonia","tonisha","tonja","tony","tonya","torey",
    "tori","toriano","torie","torin","torrance","torrey","torri","torrie","tory","tosha",
    "towanda","toya","trace","tracee","tracey","traci","tracie","tracy","trae","trajan",
    "travion","travis","travon","trayvon","tre","treasure","treena","tremaine","tremayne","trena",
    "trent","trenten","trenton","tresa","tressa","tressie","treva","trever","trevin","trevion",
    "trevon","trevor","trey","treyson","treyton","treyvon","tricia","trina","trinidad","trinitee",
    "triniti","trinity","tripp","trish","trisha","trista","tristan","tristen","tristian","tristin",
    "triston","tristyn","troy","tru","trudi","trudy","true","truett","truman","truth",
    "trystan","tucker","turkessa","turner","twana","twanna","twila","twyla","ty","tyana",
    "tyanna","tyasia","tyce","tye","tyesha","tyisha","tyla","tylan","tylar","tyler",
    "tylor","tyquan","tyra","tyree","tyreek","tyreese","tyrek","tyreke","tyrel","tyrell",
    "tyrese","tyrik","tyrin","tyriq","tyrique","tyron","tyrone","tyrus","tyshaun","tyshawn",
    "tyson","tytiana","tzvi","ulises","ulysses","umar","una","uniqua","unique","unknown",
    "unnamed","urban","uriah","uriel","urijah","ursula","uziel","vada","vaeda","vaida",
    "val","valarie","valencia","valentin","valentina","valentine","valentino","valeria","valerie","valery",
    "valinda","valkyrie","valor","valorie","van","vance","vanesa","vanessa","vania","vanity",
    "vanna","vannessa","varun","vaughn","vayda","ved","veda","veer","velda","velma",
    "velva","velvet","venessa","venita","venus","vera","verania","verda","vergie","verity",
    "verla","verlin","vern","verna","verne","vernell","vernice","vernie","vernita","vernon",
    "verona","veronica","veronika","vesta","viaan","vianey","vianney","vicente","vickey","vicki",
    "vickie","vicky","victor","victoria","vida","vidal","vienna","vihaan","vikki","viktor",
    "viktoria","vilma","vina","vince","vincent","vincenza","vincenzo","viola","violet","violeta",
    "violetta","violette","viraj","virgie","virgil","virginia","viridiana","vito","viva","vivaan",
    "vivian","viviana","vivianna","vivianne","vivien","vivienne","vladimir","von","vonda","vonetta",
    "vonnie","wade","waldo","walker","wallace","wally","walter","walton","wanda","waneta",
    "ward","warner","warren","watson","waverly","wayde","waylen","waylon","wayne","webster",
    "weldon","wells","wende","wendell","wendi","wendy","wes","wesley","wesson","westin",
    "westley","westlyn","weston","westyn","whitley","whitney","whittney","wilber","wilbert","wilbur",
    "wilburn","wilda","wilder","wiley","wilford","wilfred","wilfredo","wilhelmina","will","willa",
    "willard","willem","william","willie","willis","willow","wilma","wilmer","wilson","wilton",
    "windell","windy","winfield","winford","winfred","winifred","winnie","winnifred","winona","winston",
    "winter","witten","wolfgang","woodrow","woody","wren","wrenley","wyatt","wylder","wylie",
    "wynter","xaiden","xander","xavi","xavier","xavion","xavior","xena","ximena","xiomara",
    "xitlali","xitlaly","xochitl","xyla","xzavier","xzavion","yaakov","yadhira","yadiel","yadira",
    "yael","yahaira","yahir","yahya","yair","yaire","yajaira","yakov","yalitza","yamil",
    "yamila","yamile","yamilet","yamileth","yamilex","yana","yancy","yandel","yaneli","yanira",
    "yaquelin","yara","yarel","yareli","yarely","yaretzi","yaretzy","yariel","yaritza","yaseen",
    "yash","yashica","yasin","yasir","yasmeen","yasmin","yasmine","yatziri","yazmin","yazmine",
    "yehuda","yerik","yesenia","yeshua","yesica","yessenia","yessica","yetta","yisroel","yitty",
    "yitzchok","yocelin","yoel","yolanda","yolonda","yonatan","yosef","yoselin","yoselyn","yousef",
    "yousif","youssef","yovani","ysabella","yuliana","yulisa","yulissa","yuna","yurem","yuri",
    "yuridia","yusra","yusuf","yuvaan","yuvan","yvette","yvonne","zabdiel","zachariah","zachary",
    "zachery","zack","zackary","zackery","zaden","zadie","zahara","zahir","zahra","zaid",
    "zaida","zaiden","zaidyn","zain","zaina","zainab","zaine","zaira","zaire","zakai",
    "zakari","zakaria","zakariya","zakary","zakiya","zakiyah","zamir","zamira","zamora","zana",
    "zander","zandra","zane","zaniah","zaniya","zaniyah","zara","zarah","zaria","zariah",
    "zariya","zariyah","zavian","zavier","zavion","zaya","zayan","zayd","zayda","zayden",
    "zayla","zaylee","zaylen","zayn","zaynab","zayne","zayvion","zebulon","zechariah","zeke",
    "zelda","zelie","zella","zelma","zen","zena","zendaya","zephaniah","zephyr","zeppelin",
    "zeus","zev","zeynep","zhane","zhavia","zhuri","zia","ziggy","zina","zinnia",
    "zion","ziva","ziya","zoe","zoee","zoey","zofia","zoie","zola","zona",
    "zooey","zora","zoya","zula","zulema","zuleyka","zuri","zyair","zyaire","zyana",
    "zyla","zylah","zymir","zyon",
}


def get_first_name(full_name):
    """Extract and validate first name from lead name.

    Returns the first word if it's a recognized first name (SSA data),
    otherwise returns 'there' (for company names like 'Bridgerow Blinds').
    """
    if not full_name or not full_name.strip():
        return "there"
    first_word = full_name.strip().split()[0]
    if first_word.lower() in COMMON_FIRST_NAMES:
        return first_word.capitalize()
    return "there"


def get_city(lead, properties):
    """Extract city from lead data.

    UpNest leads have a top-level 'city' field from subject parsing.
    Seller Hub / Social Connect leads derive city from property_address.
    """
    # Direct city field (UpNest)
    city = lead.get("city", "")
    if city:
        return city

    # Extract from property_address:
    #   '123 Main St, Adrian, MI 49221' → 'Adrian' (3 parts, city at [1])
    #   '604 Brierwood Court, Ann Arbor City, MI, 48103' → 'Ann Arbor City' (4 parts, city at [1])
    #   'South Lyon, MI' → 'South Lyon' (2 parts, city at [0])
    if properties:
        addr = properties[0].get("property_address", "")
        parts = [p.strip() for p in addr.split(",")] if addr else []
        if len(parts) >= 3:
            return parts[1]
        elif len(parts) == 2:
            return parts[0]

    return ""


def format_property_list_inline(properties):
    """Format properties as inline text: '{street_1} in {city_1} and {street_2} in {city_2}'.

    2 properties: '{street_1} in {city_1} and {street_2} in {city_2}'
    3+ properties: '{street_1} in {city_1}, {street_2} in {city_2}, and {street_3} in {city_3}'

    Uses property_address when it has a real street address (3+ comma parts).
    Falls back to canonical_name for city-only addresses like 'South Lyon, MI'.
    """
    items = []
    for p in properties:
        addr = p.get("property_address", "")
        canonical = p.get("canonical_name", "")
        parts = [part.strip() for part in addr.split(",")] if addr else []
        if len(parts) >= 3:
            # Full street address: '826 N Main St, Adrian, MI 49221' → '826 N Main St in Adrian'
            street = parts[0]
            city = parts[1]
            items.append(f"{street} in {city}")
        elif canonical:
            items.append(canonical)
        elif addr:
            items.append(addr)
        else:
            items.append(p.get("property_name", ""))
    if len(items) == 0:
        return ""
    elif len(items) == 1:
        return items[0]
    elif len(items) == 2:
        return f"{items[0]} and {items[1]}"
    else:
        return ", ".join(items[:-1]) + f", and {items[-1]}"


def create_gmail_draft(oauth, to_email, subject, body, cc=None, html_signature=""):
    """Create a Gmail draft. Single API call — no custom headers.

    Gmail strips custom X- headers when sending, so we don't set any.
    Sent emails are matched back to signals by thread_id (stored in jake_signals).
    """
    creds = Credentials(
        token=oauth["access_token"],
        refresh_token=oauth["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=oauth["client_id"],
        client_secret=oauth["client_secret"]
    )
    service = build('gmail', 'v1', credentials=creds)

    html_body = body.replace('\n', '<br>')
    if html_signature:
        html_body = html_body + '<br><br>' + html_signature
    message = MIMEText(html_body, 'html')
    message['to'] = to_email
    message['subject'] = subject
    if cc:
        message['cc'] = cc
    message['bcc'] = 'leads@resourcerealtygroupmi.com'

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    draft = service.users().drafts().create(
        userId='me',
        body={'message': {'raw': raw}}
    ).execute()

    return {
        "draft_id": draft['id'],
        "thread_id": draft['message']['threadId']
    }


def get_html_signature(source, template_used, sig_config):
    """Look up the HTML signature for a given source/template from the signer config."""
    signers = sig_config.get("signers", {})
    if not signers:
        # Hardcoded fallback when email_signatures config is missing
        src = source.lower()
        if src in ("crexi", "loopnet", "bizbuysell") or template_used.startswith(("bizbuysell_", "commercial_")) or template_used == "lead_magnet":
            return "Talk soon,<br>Larry<br>(734) 732-3789"
        else:
            return "Talk soon,<br>Andrea<br>(734) 223-1015"

    # Check template_used first (in-flight thread continuity)
    template_map = sig_config.get("template_to_signer", {})
    signer_key = template_map.get(template_used)
    if signer_key:
        signer = signers.get(signer_key, {})
        if signer:
            return signer.get("html_signature", "")

    # Fall back to source classification (flat map: source_type → signer key)
    src = source.lower()
    source_map = sig_config.get("source_to_signer", {})
    signer_key = source_map.get(src)
    if signer_key:
        signer = signers.get(signer_key, {})
        if signer:
            return signer.get("html_signature", "")

    # Default
    default_key = sig_config.get("default_signer", "larry")
    return signers.get(default_key, {}).get("html_signature", "")


def main(grouped_data: dict):
    standard_leads = grouped_data.get("standard_leads", [])
    info_requests = grouped_data.get("info_requests", [])
    drafts = []

    # Get Gmail OAuth credentials and signer config
    gmail_oauth = wmill.get_resource("f/switchboard/gmail_oauth")
    try:
        sig_config = json.loads(wmill.get_variable("f/switchboard/email_signatures"))
    except Exception:
        sig_config = {}

    for lead in standard_leads:
        first_name = get_first_name(lead["name"])
        email = lead["email"]
        phone = lead.get("phone", "")
        source = lead.get("source", "")
        source_type = lead.get("source_type", "")
        is_followup = lead.get("is_followup", False)
        properties = lead.get("properties", [])
        has_lead_magnet = any(p.get("lead_magnet") for p in properties)
        non_magnet_props = [p for p in properties if not p.get("lead_magnet")]
        is_commercial = source.lower() in ("crexi", "loopnet")
        is_bizbuysell = source.lower() == "bizbuysell"
        # Note: UpNest/Social Connect buyers also match here by source, but they
        # exit at priority 2 (buyer check) before this flag is consulted at priority 3
        is_residential_seller = source.lower() in ("seller hub", "social connect", "upnest")

        draft = {
            "name": lead["name"],
            "email": email,
            "phone": phone,
            "cc": "",
            "from_email": "teamgotcher@gmail.com",
            "source": source,
            "source_type": source_type,
            "is_new": lead.get("is_new", True),
            "is_followup": is_followup,
            "wiseagent_client_id": lead.get("wiseagent_client_id"),
            "properties": properties,
            "notification_message_ids": lead.get("notification_message_ids", []),
            "lead_type": lead.get("lead_type", ""),
            "has_nda": lead.get("has_nda", False)
        }

        # --- Template selection (order matters) ---

        # 1. Realtor.com (residential buyer, signed Andrea)
        if source.lower() == "realtor.com":
            prop = properties[0] if properties else {}
            addr = prop.get("property_address") or prop.get("canonical_name", "your property")
            canonical = prop.get("canonical_name", addr)
            draft["email_subject"] = f"RE: Your Realtor.com inquiry in {canonical}"
            draft["email_body"] = f"Hey {first_name},\n\nI received your Realtor.com inquiry about {addr}. If you'd like more information, just let me know and I'll be more than happy to answer any questions you may have. Should you want to view the property, just let me know the best day and time that works for you and I'll get that scheduled. Keep in mind the sooner the better as properties are selling quick.\n\nIf you'd rather talk over the phone, my direct line is (734) 223-1015. Please do not hesitate to reach out with any questions or concerns."
            draft["sms_body"] = f"Hey {first_name}, this is Andrea. I received your Realtor.com inquiry about {addr}. If you'd like more information or to schedule a tour, just let me know the best day & time that works for you and I'll get that scheduled. Keep in mind the sooner, the better as properties sell quickly." if phone else None
            draft["template_used"] = "realtor_com"

        # 2. UpNest / Social Connect buyer (residential buyer, signed Andrea)
        elif source.lower() in ("upnest", "social connect") and lead.get("lead_type") == "buyer":
            city = get_city(lead, properties)
            city_text = f" in {city}" if city else ""
            draft["email_subject"] = "Introductions, Buying a home?"
            draft["email_body"] = f"Hey {first_name},\n\nI got your information off of {source}. They indicated you might be looking to purchase a home{city_text} soon. If you're open to it, I'd love to schedule a time to discuss further. My direct line is (734) 223-1015. Please do not hesitate to reach out with any questions or concerns."
            draft["sms_body"] = f"Hey {first_name}, this is Andrea from Resource Realty Group. I got your info from {source}. Are you looking to purchase a home{city_text}? I'd love to sit down and discuss. My direct line is (734) 223-1015." if phone else None
            draft["template_used"] = "residential_buyer"

        # 3. Residential seller (Seller Hub, Social Connect, UpNest sellers — signed Andrea)
        elif is_residential_seller:
            city = get_city(lead, properties)
            city_text = f" in {city}" if city else ""
            draft["email_subject"] = "Introductions, Selling your home?"
            draft["email_body"] = f"Hey {first_name},\n\nI got your information off of {source}. They indicated you might be interested in selling your home{city_text}. If you're open to it, I'd love to schedule a time to sit down and discuss more. My direct line is (734) 223-1015. Please do not hesitate to reach out with any questions or concerns."
            draft["sms_body"] = f"Hey {first_name}, this is Andrea from Resource Realty Group. I got your info from {source}. Are you thinking about selling your home{city_text}? I'd love to sit down and discuss. My direct line is (734) 223-1015." if phone else None
            draft["template_used"] = "residential_seller"

        # 4. BizBuySell (business listings, signed Larry)
        elif is_bizbuysell:
            if has_lead_magnet and not non_magnet_props:
                magnet = properties[0]
                canonical = magnet.get("canonical_name", "")
                addr = magnet.get("property_address") or canonical
                draft["email_subject"] = f"RE: Your Interest in {canonical}"
                draft["email_body"] = f"Hey {first_name},\n\nI got your information when you checked out my listing for {addr}. That business is no longer available, but we have some similar businesses that might be a good fit depending on what you're looking for.\n\nIf you'd like to check out what we have, just let me know and I can send over some information. We also have some off-market opportunities that would require an NDA to be signed.\n\nIf you'd rather talk over the phone, my direct line is (734) 732-3789. Please do not hesitate to reach out with any questions or concerns."
                draft["sms_body"] = f"Hey {first_name}, this is Larry from Resource Realty Group. I saw you checked out {canonical}. That one's no longer available, but I have some similar businesses. Let me know if you're interested! My direct line is (734) 732-3789." if phone else None
                draft["template_used"] = "bizbuysell_lead_magnet"
            elif len(properties) > 1:
                if is_followup:
                    draft["email_subject"] = "RE: Your Interest in Multiple Businesses"
                    draft["email_body"] = f"Hey {first_name},\n\nI see you checked out a few more of my listings. If you'd like to check out more information on any of these, just let me know and I'll send over the OMs."
                    draft["sms_body"] = f"Hey {first_name}, I see you checked out a few more of my listings. Let me know if you'd like the OMs on any of them! - Larry" if phone else None
                    draft["template_used"] = "bizbuysell_multi_followup"
                else:
                    prop_text = format_property_list_inline(non_magnet_props or properties)
                    draft["email_subject"] = "RE: Your Interest in Multiple Businesses"
                    draft["email_body"] = f"Hey {first_name},\n\nI got your information off of {source} when you checked out {prop_text}.\n\nIf you'd like to check out more information on any of these, just let me know and I'll send over the OMs.\n\nAlternatively, we also have some off-market opportunities that might be a good fit, depending on what you're looking for. They would require an NDA to be signed, so just let me know and I can send one over to you.\n\nIf you'd rather talk over the phone, my direct line is (734) 732-3789. Please do not hesitate to reach out with any questions or concerns."
                    draft["sms_body"] = f"Hey {first_name}, this is Larry from Resource Realty Group. I saw you checked out a few of my business listings on {source}. Let me know if you'd like more info on any of them! My direct line is (734) 732-3789." if phone else None
                    draft["template_used"] = "bizbuysell_multi_first_contact"
            else:
                prop = properties[0] if properties else {}
                addr = prop.get("property_address") or prop.get("canonical_name", "the business")
                canonical = prop.get("canonical_name", addr)
                if is_followup:
                    draft["email_subject"] = f"RE: Your Interest in {canonical}"
                    draft["email_body"] = f"Hey {first_name},\n\nI see you checked out another business listing - {addr}.\n\nIf you'd like to check out more information on this one, just let me know and I'll send over the OM."
                    draft["sms_body"] = f"Hey {first_name}, I see you checked out another business listing - {addr}. Let me know if you'd like the OM on this one! - Larry" if phone else None
                    draft["template_used"] = "bizbuysell_followup"
                else:
                    draft["email_subject"] = f"RE: Your Interest in {canonical}"
                    draft["email_body"] = f"Hey {first_name},\n\nI got your information off of {source} when you checked out my business listing, {addr}.\n\nIf you'd like to check out more information, just let me know and I'll send over the OM so you can check it out.\n\nAlternatively, we also have some off-market opportunities that might be a good fit, depending on what you're looking for. They would require an NDA to be signed, so just let me know and I can send one over to you.\n\nIf you'd rather talk over the phone, my direct line is (734) 732-3789. Please do not hesitate to reach out with any questions or concerns."
                    draft["sms_body"] = f"Hey {first_name}, this is Larry from Resource Realty Group. I got your information off of {source} when you checked out my business listing, {addr}. If you'd like more info, just let me know and I'll send over the OM. My direct line is (734) 732-3789." if phone else None
                    draft["template_used"] = "bizbuysell_first_outreach"

        # 5. Lead magnet — all properties are lead_magnet (signed Larry for commercial)
        elif has_lead_magnet and not non_magnet_props:
            magnet = properties[0]
            canonical = magnet.get("canonical_name", "")
            addr = magnet.get("property_address") or canonical
            draft["email_subject"] = f"RE: Your Interest in {canonical}"
            draft["email_body"] = f"Hey {first_name},\n\nI got your information when you checked out my listing for {addr}. That property is no longer available, but we have some similar properties that might be a good fit depending on what you're looking for.\n\nIf you'd like to check out what we have, just let me know and I can send over some information. We also have some off-market properties that would require an NDA to be signed.\n\nIf you'd rather talk over the phone, my direct line is (734) 732-3789. Please do not hesitate to reach out with any questions or concerns."
            draft["sms_body"] = f"Hey {first_name}, this is Larry from Resource Realty Group. I saw you checked out {canonical}. That one's no longer available, but I have some similar properties. Let me know if you're interested! My direct line is (734) 732-3789." if phone else None
            draft["template_used"] = "lead_magnet"

        # 6-9. Commercial (Crexi/LoopNet) — signed Larry
        elif is_commercial:
            if len(properties) > 1:
                # Multi-property
                if is_followup:
                    # 6. commercial_multi_property_followup
                    draft["email_subject"] = "RE: Your Interest in Multiple Properties"
                    draft["email_body"] = f"Hey {first_name},\n\nI see you checked out a few more of my listings. If you'd like to check out more information on any of these, just let me know and I'll send over the OMs."
                    draft["sms_body"] = f"Hey {first_name}, I see you checked out a few more of my listings. Let me know if you'd like the OMs on any of them! - Larry" if phone else None
                    draft["template_used"] = "commercial_multi_property_followup"
                else:
                    # 7. commercial_multi_property_first_contact
                    prop_text = format_property_list_inline(non_magnet_props or properties)
                    draft["email_subject"] = "RE: Your Interest in Multiple Properties"
                    draft["email_body"] = f"Hey {first_name},\n\nI got your information off of {source} when you checked out {prop_text}.\n\nIf you'd like to check out more information on any of these, just let me know and I'll send over the OMs.\n\nAlternatively, we also have some off-market properties that might be a good fit, depending on what you're looking for. They would require an NDA to be signed, so just let me know and I can send one over to you.\n\nIf you'd rather talk over the phone, my direct line is (734) 732-3789. Please do not hesitate to reach out with any questions or concerns."
                    draft["sms_body"] = f"Hey {first_name}, this is Larry from Resource Realty Group. I saw you checked out a few of my properties on {source}. Let me know if you'd like more info on any of them! My direct line is (734) 732-3789." if phone else None
                    draft["template_used"] = "commercial_multi_property_first_contact"
            else:
                # Single property
                prop = properties[0] if properties else {}
                addr = prop.get("property_address") or prop.get("canonical_name", "the property")
                canonical = prop.get("canonical_name", addr)
                if is_followup:
                    # 8. commercial_followup_template
                    draft["email_subject"] = f"RE: Your Interest in {canonical}"
                    draft["email_body"] = f"Hey {first_name},\n\nI see you checked out another property - {addr}.\n\nIf you'd like to check out more information on this one, just let me know and I'll send over the OM."
                    draft["sms_body"] = f"Hey {first_name}, I see you checked out another property - {addr}. Let me know if you'd like the OM on this one! - Larry" if phone else None
                    draft["template_used"] = "commercial_followup_template"
                else:
                    # 9. commercial_first_outreach_template
                    draft["email_subject"] = f"RE: Your Interest in {canonical}"
                    draft["email_body"] = f"Hey {first_name},\n\nI got your information off of {source} when you checked out my property, {addr}.\n\nIf you'd like to check out more information, just let me know and I'll send over the OM so you can check it out.\n\nAlternatively, we also have some off-market properties that might be a good fit, depending on what you're looking for. They would require an NDA to be signed, so just let me know and I can send one over to you.\n\nIf you'd rather talk over the phone, my direct line is (734) 732-3789. Please do not hesitate to reach out with any questions or concerns."
                    draft["sms_body"] = f"Hey {first_name}, this is Larry from Resource Realty Group. I got your information off of {source} when you checked out my property, {addr}. If you'd like more info, just let me know and I'll send over the OM. My direct line is (734) 732-3789." if phone else None
                    draft["template_used"] = "commercial_first_outreach_template"

        # 10. Unknown source type — skip (no draft)
        else:
            continue

        # Look up HTML signature for this draft's source/template
        draft["html_signature"] = get_html_signature(source, draft.get("template_used", ""), sig_config)

        drafts.append(draft)

    # Now create Gmail drafts for each lead
    for draft in drafts:
        try:
            result = create_gmail_draft(
                gmail_oauth,
                draft["email"],
                draft["email_subject"],
                draft["email_body"],
                cc=draft.get("cc"),
                html_signature=draft.get("html_signature", "")
            )

            # Store Gmail draft info (thread_id is used for SENT matching)
            draft["gmail_draft_id"] = result["draft_id"]
            draft["gmail_message_id"] = None
            draft["gmail_thread_id"] = result["thread_id"]
            draft["draft_created_at"] = datetime.now(timezone.utc).isoformat()
            draft["draft_creation_success"] = True

        except Exception as e:
            draft["gmail_draft_id"] = None
            draft["gmail_message_id"] = None
            draft["gmail_thread_id"] = None
            draft["draft_created_at"] = datetime.now(timezone.utc).isoformat()
            draft["draft_creation_success"] = False
            draft["draft_creation_error"] = str(e)

        # Remove html_signature from draft — already baked into the Gmail draft
        draft.pop("html_signature", None)

    # Generate summary
    new_count = sum(1 for d in drafts if d.get("is_new"))
    existing_count = len(drafts) - new_count
    successful_drafts = sum(1 for d in drafts if d.get("draft_creation_success"))

    preflight = {
        "scan_complete": True,
        "parse_complete": True,
        "crm_lookup_complete": True,
        "property_match_complete": True,
        "drafts_complete": True,
        "gmail_drafts_created": successful_drafts,
        "total_leads": len(drafts),
        "new_contacts": new_count,
        "existing_contacts": existing_count,
        "info_requests": len(info_requests),
        "multi_property": grouped_data.get("multi_property_count", 0)
    }

    summary = f"Lead Intake: {len(drafts)} leads ready | {new_count} new, {existing_count} existing | {successful_drafts} drafts created | {len(info_requests)} info requests"

    return {
        "preflight_checklist": preflight,
        "drafts": drafts,
        "info_requests": info_requests,
        "summary": summary
    }
