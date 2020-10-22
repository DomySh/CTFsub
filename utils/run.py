#!/usr/bin/python3
'''

CTFsub(mitter) for CTF A/D

Author: DomySh (Domingo Dirutigliano)
Contact: me@domysh.com
Website: www.domysh.com

'''
try:
    import utils
except:
    exit("Utils not founed!")
try:
    from utils.config import GLOBAL_LOG_FILE, GLOBAL_FLAG_FILE
except:
    exit("Failed to import PATH to logs from config")

try:
    import multiprocessing, time, threading
    import importlib, re
    from time import sleep
    from utils.syjson import SyJson
except:
    exit("Failed to import some libraries")

try:
    from utils.config import GLOBAL_DATA_FILE, GLOBAL_SETTINGS_FILE, FLAG_REGEX, flag_submit, ATTACK_PKG
    from utils.config import SHELL_CAN_USE, TIMES_TO_BLACKLIST, ATTACKS_FOLDER, TEAM_IP_RANGE, SEC_SECONDS, TIMEOUT_ATTACK
    from utils.config import OUR_TEAM_ID, IP_VM_TEMP, THREADING_LIMIT, AUTO_BLACKLIST_ON, TIME_TO_WAIT_IN_BLACKLIST, TICK_TIME
except Exception as e:
    exit("Failed to import some configs: "+str(e))
try:
    log = utils.fun.setup_logger('CTFsub',GLOBAL_LOG_FILE)
    flag_log = utils.fun.setup_logger('flags',GLOBAL_FLAG_FILE,'%(asctime)s FLAG: %(message)s')
except:
    exit("Failed to create log objects")
#global vars synced with relative files
class glob: 
    constant_vars = SyJson(GLOBAL_DATA_FILE)
    settings = SyJson(GLOBAL_SETTINGS_FILE)
    break_wait_time = False
    break_round_attacks = False

#Function used for submit a flag
def submit_flag(flags:list):
    if not FLAG_REGEX is None:
        #Filtering all recived flags
        flags = re.findall(FLAG_REGEX," ".join(flags)) 
    sended = []
    for flag in flags:
        if flag not in sended:
            try:
                flag_log.info(flag)
                flag_submit(flag)
                log.info(f'Submitted to gameserver "{flag}" flag')
                sended.append(flag)
            except Exception as e:
                log.error(f'Submission of "{flag}" flag, FAILED!, see flag log for details')
                flag_log.exception(e)
    del sended

#Get python module file of the attack and use it
def get_attack_by_name(attack_name,cache_use = False):
    res = getattr(__import__(f"{ATTACK_PKG}.{attack_name}"),attack_name)
    res = importlib.reload(res) #You you change the program this will change instantly
    return res

def shell_request_manage():
    try:
        if 'shell_req' in glob.settings.keys():
            req = glob.settings['shell_req']
            if 'wait_for' in req.keys():
                if req['wait_for'] == 'sub':
                    try:
                        if shell_reqest_dispatcher(req['id_req'],req):
                            req['wait_for'] = 'shell'
                        else:
                            glob.settings['shell_req'] = {}
                    except Exception as e:
                        log.error('Failed to execute shell requests')
                        log.exception(e)
                elif req['wait_for'] is None:
                    glob.settings['shell_req'] = {}

    except Exception as e:
        log.error('Failed to read shell requests')
        log.exception(e)

def shell_reqest_dispatcher(action,req_dict):
    if action == 'break-wait-time':
        if not glob.break_wait_time:
            log.info('Requested from shell to skip wait time for this round')
            glob.break_wait_time = True
    elif action == 'stop-attacks':
        if not glob.break_round_attacks:
            log.info('Requested from shell to stop attacks for this round')
            glob.break_round_attacks = True
    elif action == 'config':
        if req_dict['operation_type'] == 'get':
            config_name = req_dict['target_key']
            if config_name in SHELL_CAN_USE:
                req_dict['response_value'] = getattr(utils.config, config_name)
                return True
        elif req_dict['operation_type'] == 'set':
            config_name = req_dict['target_key']
            if config_name in SHELL_CAN_USE:
                setattr(utils.config, config_name, req_dict['target_value'])
                log.info(f'utils.config.{config_name} assigned to {req_dict["target_value"]}')
        elif req_dict['operation_type'] == 'list':
            names = SHELL_CAN_USE
            values = []
            for name in names:
                values.append(getattr(utils.config, name))
            req_dict['response_values'] = values
            req_dict['response_names'] = names
            return True

    else:
        log.info('Unrecognised shell request... skipping')
    return None

#Thread function that have to execute a function
def start_attack(py_attack, assigned_ip):
    #Starting the attack...
    try:
        #Import the file and importing an Istance of the Attack Class
        this_attack = get_attack_by_name(py_attack).ATTACK
        this_attack.attack_name = utils.fun.min_name(py_attack)
        #Verify that is the sub class wanted
        if not isinstance(this_attack, utils.classes.AttackModel):
            log.error(f'{py_attack} file havent a Attack Class that is subclass of AttackModel... Skipping attack...')
            return
        #Get the flag and submit
        flags_obtained = 'leak_closed'

        #Get attack settings
        attack_settings = glob.settings['process_controller'][py_attack]

        #Managing alive control for the remote service
        if not (attack_settings['alive_ctrl'] is None):
            #if wanted as decribed in the attack file, we control first if the service is on
            if not utils.fun.is_port_in_use(assigned_ip,attack_settings['alive_ctrl']):
                log.warning(f'We found closed port attacking {assigned_ip}:{attack_settings["alive_ctrl"]} with {py_attack} attack')
                return

        #Queue for get the result from Process used for put a TIMEOUT at the attack
        res = multiprocessing.Queue()

        var_dict = glob.constant_vars[this_attack.attack_name][assigned_ip].var()
        # choose what timeout time to use
        timeout_process = TIMEOUT_ATTACK
        if not attack_settings['timeout'] is None:
            timeout_process = attack_settings['timeout']

        #Start the process
        p = multiprocessing.Process(target=this_attack.get_flags,args=(assigned_ip, var_dict, res))
        p.start()
        p.join(timeout_process)

        # If thread is still active we kill it
        if p.is_alive():
            log.info(f'{py_attack} on {assigned_ip} This thread taked over {timeout_process} seconds, killing...')
            p.terminate()
            p.join()
        else:
            #get the result (sending the flag and saving changes of permanent vars)
            flags_obtained = res.get()
            glob.constant_vars[this_attack.attack_name][assigned_ip].sync(res.get())
        
        del this_attack
        
        #Updating the status of auto blacklist
        blacklist_status = glob.settings['blacklist'][py_attack][assigned_ip]

        if flags_obtained is None or flags_obtained == 'leak_closed':
            #If this attack is a try to re-attack a team that probably have closed the vuln
            if blacklist_status['stopped_times'] == -1 and blacklist_status['excluded']:
                blacklist_status['stopped_times'] = 0
            else:
                #Count fail time, if it fails enougth times, we put it in the auto blacklist
                blacklist_status['fail_times'] += 1
                if blacklist_status['fail_times'] >= TIMES_TO_BLACKLIST:
                    #Start auto blacklist
                    blacklist_status['excluded'] = True
                    blacklist_status['stopped_times'] = 0


        #Send a different message on log for different situations
        if flags_obtained is None: # Unexpected error
            log.error(f'unexpected error attacking {assigned_ip} using {py_attack} attack have been raised')
        elif flags_obtained == 'leak_closed': #Attack failed (Because the leak is closed)
            log.warning(f'Attack to {assigned_ip} using {py_attack} attack FAILED (leak closed)!')
        elif flags_obtained == 'service_closed': # Service not reponding or take lot's of time
            log.warning(f'Find closed service to {assigned_ip} using {py_attack} attack !')
        else:
            # if the attack went successfully send the flag and reset blacklist status (Usefull for an attack reopened)
            blacklist_status = {
                    'excluded':False,
                    'fail_times':0,
                    'stopped_times':0
            }
            submit_flag(flags_obtained)
            
    #Fail case (return result form attack script isn't what we expected)
    except Exception as e:
        log.error(f'An unexpected result recived on {assigned_ip} using {py_attack} attack... continuing')
        log.exception(e)

def main():
    log.info('CTFsub is starting !')
    while True:
        #Wait for find python attack files
        wait_for_attacks = False
        #Remove Pycache
        while True:  
            #Taking the list of the python executable to run for the attack
            to_exec = [f for f in utils.fun.get_pythonfile_list(ATTACKS_FOLDER) if f != '__init__'] 
            if len(to_exec) == 0:
                if wait_for_attacks == False:
                    log.info('Waiting for attacks python files')
                    wait_for_attacks = True
                time.sleep(.1)
            else:
                if wait_for_attacks == True:
                    log.info('Python attack file found! STARTING...')
                break
            
        #Get start time for calculating at the end of the attack how many time have to wait
        last_time = time.time()
        
        # Start the round
        flag_log.info('ROUND STARTED')
        log.info('Round Started')
        thread_list = []
        for py_f in to_exec: #Starting attacks ! 

            log.info(f'STARTING {py_f} attack!')

            # repeating the attack for every team 
            for team_id in range( TEAM_IP_RANGE[0], TEAM_IP_RANGE[1]+1): 

                if team_id == OUR_TEAM_ID: continue # Skiping our team
                #calculating the ip
                ip_to_attack = utils.fun.get_ip_from_temp(IP_VM_TEMP, {'team_id':team_id}) 

                if glob.break_round_attacks:break #break attack as requested
                
                #Wait for a free thread following the THREADING_LIMIT
                while len(thread_list) >= THREADING_LIMIT:
                    #Wait for a free thread
                    shell_request_manage()    
                    for i in range(len(thread_list)):
                        if not thread_list[i].is_alive():
                            thr = thread_list.pop(i); del thr
                            break
                    time.sleep(.1)
                

                # Controlling and creating blacklist and process_controller for every attack
                if 'blacklist' not in glob.settings.keys():
                    glob.settings['blacklist'] = {}
                
                if 'process_controller' not in glob.settings.keys():
                    glob.settings['process_controller'] = {}

                if py_f not in glob.settings['blacklist'].keys():
                    glob.settings['blacklist'][py_f] = {}

                if ip_to_attack not in glob.settings['blacklist'][py_f].keys():
                    glob.settings['blacklist'][py_f][ip_to_attack] = {
                        'excluded':False,
                        'fail_times':0,
                        'stopped_times':0
                    }
                

                if py_f not in glob.settings['process_controller'].keys():
                    glob.settings['process_controller'][py_f] = {
                        'alive_ctrl':None,
                        'on':True,
                        'whitelist_on':False,
                        'excluded_ip':[],
                        'whitelist_ip':[],
                        'timeout':None
                    }
                    # Try to charge all specific configs from the attack file
                    try:
                        atk = get_attack_by_name(py_f)
                        if 'CONFIG' in dir(atk):
                            for k_settings in glob.settings['process_controller'][py_f].keys():
                                if k_settings in atk.CONFIG.keys():
                                    glob.settings['process_controller'][py_f][k_settings] = atk.CONFIG[k_settings]
                        del atk
                    except Exception as e:
                        log.error('ERROR LOADING CONFIG FROM ATTACK')
                        log.exception(e)
                
 

                attack_blacklist = glob.settings['blacklist'][py_f][ip_to_attack]
                attack_settings = glob.settings['process_controller'][py_f]
                

                #Choose what action do following the istruction in settings dict
                if attack_settings['on']: # If the attack is enabled
                    #Control list controls
                    if attack_settings['whitelist_on']: #Filtering with blacklist or withlist
                        #Filter whitelist
                        if ip_to_attack not in attack_settings['whitelist_ip']:
                            continue
                    else:
                        #Filter blacklist
                        if ip_to_attack in attack_settings['excluded_ip']:
                            log.warning(f'{py_f} attack on IP {ip_to_attack} in blacklist... skipping')
                            continue
                    #Auto blacklist control
                    if AUTO_BLACKLIST_ON:
                        if attack_blacklist['excluded']:
                            if attack_blacklist['stopped_times'] == -1:
                                pass # Last time the service was closed so we have to try again to attack
                            if attack_blacklist['stopped_times'] >= TIME_TO_WAIT_IN_BLACKLIST:
                                log.warning(f'auto_blacklist enabled on ip {ip_to_attack} of {py_f} attack ... trying anyway to execute')
                                attack_blacklist['stopped_times'] = -1 # If success -1 remember to reset blacklist
                            else:
                                log.warning(f'auto_blacklist enabled on ip {ip_to_attack} of {py_f} attack ... skipping')
                                attack_blacklist['stopped_times'] += 1
                                continue
                else:
                    log.warning(f'{py_f} attack disabilited! Skipping...')
                    break
                
                #Set up structure for save permanent vars
                if py_f not in glob.constant_vars.keys():
                    glob.constant_vars[py_f] = {}
                    glob.constant_vars[py_f][ip_to_attack] = {}
                elif ip_to_attack not in glob.constant_vars[py_f].keys():
                    glob.constant_vars[py_f][ip_to_attack] = {}

                #Starting new thread for attack
                log.info(f'Starting thread {py_f} attack for {ip_to_attack}')
                thread_list.append(threading.Thread(target=start_attack,args=(py_f,ip_to_attack)))
                thread_list[-1].daemon = True
                thread_list[-1].start()

            log.info(f'{py_f} attack, finished!')
            if glob.break_round_attacks:break #break attack as requested
            
        #Wait for threads work finish
        log.info('Waiting for thread work finish')
        if glob.break_round_attacks: glob.break_round_attacks = False #Attack breaked!
        while len(thread_list) != 0:
            #Wait for a free thread
            time.sleep(.1)
            shell_request_manage()
            for i in range(len(thread_list)):
                if not thread_list[i].is_alive():
                    thr = thread_list.pop(i); del thr
                    break
        del thread_list
        log.info(f'Attacks for this round finished')

        #Wait remaing time
        time_to_wait = TICK_TIME - (time.time() - last_time)
        if time_to_wait > 0:
            log.info(f'{int(time_to_wait//60)} minutes and {int(time_to_wait)%60} seconds for new round')
            while time_to_wait > 0:
                time_to_wait = TICK_TIME - (time.time() - last_time)
                shell_request_manage()
                if glob.break_wait_time:break
                sleep(0.1)
        
        if glob.break_wait_time:
            glob.break_wait_time = False
        else:
            # Adding SEC_SECONDS seconds
            for i in reversed(range(1,SEC_SECONDS+1)):
                log.warning(f'{i} second for starting new round')
                sleep(1)


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt,InterruptedError):
        log.fatal('CTRL+C Pressed, Closing')
        print()
        exit()

    